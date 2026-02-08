# Astrbook Redis 迁移计划

> 创建日期: 2025-07-15  
> 最后更新: 2026-02-08  
> 状态: 实施中（基础设施 ✅ · Phase 0 ✅ · Phase 1 待开始 · Phase 2 待开始）

---

## 目录

- [一、迁移背景与目标](#一迁移背景与目标)
- [二、基础设施搭建](#二基础设施搭建)
- [三、Phase 0 — 多实例部署必须](#三phase-0--多实例部署必须)
- [四、Phase 1 — 核心性能优化](#四phase-1--核心性能优化)
- [五、Phase 2 — 锦上添花](#五phase-2--锦上添花)
- [六、文件改动清单](#六文件改动清单)
- [七、Redis Key 规范总表](#七redis-key-规范总表)
- [八、风险与降级策略](#八风险与降级策略)
- [九、测试计划](#九测试计划)
- [十、预期收益](#十预期收益)

---

## 一、迁移背景与目标

### 当前问题

项目中存在 **4 个内存缓存/状态字典** 和 **1 个内存速率限制器**，全部仅限单进程有效：

| 内存状态 | 所在文件 | 问题 |
|----------|----------|------|
| `_user_cache` | `auth.py` | 多实例用户缓存不一致 |
| `_oauth_states` | `routers/oauth.py` | 多实例 OAuth 回调 100% 失败 |
| `_moderator_cache` | `moderation.py` | 多实例审核配置不同步 |
| `Limiter(内存存储)` | `rate_limit.py` | 多实例限流形同虚设 |
| `SSEManager._connections` | `sse.py` | 跨实例 SSE 推送不可达 |

### 迁移目标

1. **支持多实例水平扩展** — 所有进程间共享状态迁移到 Redis
2. **减少 DB 查询** — 高频读路径增加 Redis 缓存层，平均每请求 DB 查询从 4-6 次降至 1-3 次
3. **降低关键路径延迟** — 未读计数轮询从 4-10ms 降至 ~0.3ms
4. **保持向后兼容** — Redis 可选依赖，宕机时自动降级回 DB 直查

---

## 二、基础设施搭建

> 预计工时：0.5 天

### 2.1 新增依赖

```diff
# requirements.txt
+ redis[hiredis]>=5.0.0
```

`hiredis` 是 C 实现的 Redis 协议解析器，性能约为纯 Python 解析器的 10 倍。

### 2.2 新增配置项

```python
# config.py — Settings 类新增
REDIS_URL: str = ""  # 为空时禁用 Redis，全部降级回本地内存/DB 直查
```

**设计决策**：`REDIS_URL` 默认空字符串，当用户未配置 Redis 时，系统保持当前行为不变（内存缓存 + DB 直查），实现渐进式迁移。

### 2.3 新建 `redis_client.py`

```python
# server/app/redis_client.py

"""
Redis 连接管理器

- 提供全局连接池（decode_responses=True）
- 支持 Redis 不可用时的优雅降级
- 提供 get_redis() 依赖注入
"""

import logging
import redis.asyncio as aioredis
from typing import Optional
from .config import get_settings

logger = logging.getLogger(__name__)

_pool: Optional[aioredis.Redis] = None

async def init_redis():
    """初始化 Redis 连接池（app startup 时调用）"""
    global _pool
    settings = get_settings()
    if not settings.REDIS_URL:
        logger.info("[Redis] REDIS_URL 未配置，Redis 缓存已禁用")
        return
    try:
        _pool = aioredis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            max_connections=20
        )
        await _pool.ping()
        logger.info(f"[Redis] 连接成功: {settings.REDIS_URL}")
    except Exception as e:
        logger.warning(f"[Redis] 连接失败，将降级回本地模式: {e}")
        _pool = None

async def close_redis():
    """关闭 Redis 连接池（app shutdown 时调用）"""
    global _pool
    if _pool:
        await _pool.aclose()
        _pool = None

def get_redis() -> Optional[aioredis.Redis]:
    """获取 Redis 客户端，未初始化或连接失败返回 None"""
    return _pool
```

### 2.4 生命周期注册

```python
# main.py 改动

from .redis_client import init_redis, close_redis

@app.on_event("startup")
async def startup_event():
    await init_redis()

@app.on_event("shutdown")
async def shutdown_event():
    # 现有 httpx 关闭逻辑...
    await close_redis()
```

---

## 三、Phase 0 — 多实例部署必须

> 预计工时：1 天  
> 不完成这些，多实例部署会出现功能性 bug

### P0-1. OAuth State 迁移

**文件**：`routers/oauth.py`

**当前实现**：
```python
# 第 30 行 — 进程内字典，多实例不共享
_oauth_states: dict[str, dict] = {}
_STATE_TTL = 600  # 10 分钟
```

**问题**：用户在实例 A 发起 OAuth，回调命中实例 B → state 找不到 → 登录失败。

**迁移方案**：
```python
import json
from ..redis_client import get_redis

async def _set_oauth_state(state: str, data: dict):
    """存储 OAuth state 到 Redis（TTL 自动过期，无需手动清理）"""
    r = get_redis()
    if r:
        await r.setex(f"oauth:state:{state}", _STATE_TTL, json.dumps(data))
    else:
        # 降级：保留原字典逻辑
        _oauth_states[state] = {**data, "_ts": _time.time()}

async def _pop_oauth_state(state: str) -> dict | None:
    """取出 OAuth state（Redis 中取出即删）"""
    r = get_redis()
    if r:
        raw = await r.getdel(f"oauth:state:{state}")
        return json.loads(raw) if raw else None
    else:
        # 降级：原逻辑
        data = _oauth_states.pop(state, None)
        if data and _time.time() - data.get("_ts", 0) > _STATE_TTL:
            return None
        return data
```

**附带修复 Bug**：第 106 行 `github_callback` 中误用了 `oauth_states.pop(state, None)` 而非 `_pop_oauth_state(state)`，绕过了过期检查。迁移时统一改为 `await _pop_oauth_state(state)`。

**改动点**：
- `_set_oauth_state()` → 改为 async，内部写 Redis
- `_pop_oauth_state()` → 改为 async，内部读删 Redis
- 调用方（4 处）加 `await`
- 移除手动过期清理逻辑（Redis TTL 代替）
- 修复第 106 行 bug

---

### P0-2. 用户认证缓存迁移

**文件**：`auth.py`

**当前实现**：
```python
# 第 23-25 行 — 进程内字典 + threading.Lock
_user_cache: dict[int, tuple[User, float]] = {}
_user_cache_lock = threading.Lock()
_USER_CACHE_TTL = 60
```

**迁移方案**：

```python
import json
from .redis_client import get_redis

_USER_CACHE_TTL = 300  # 提升到 5 分钟（Redis 比内存 dict 更可靠）

def _user_to_cache(user: User) -> str:
    """序列化用户对象为 JSON（只缓存认证所需字段）"""
    return json.dumps({
        "id": user.id,
        "username": user.username,
        "nickname": user.nickname,
        "avatar": user.avatar,
        "is_banned": user.is_banned,
        "ban_reason": user.ban_reason,
        "bio": user.bio,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    })

def _user_from_cache(data: str, db: Session) -> User:
    """从 JSON 反序列化并绑定到当前 Session"""
    d = json.loads(data)
    user = User(**d)
    return db.merge(user, load=False)
```

**关键设计**：
- 序列化只存认证必需字段，不存密码 hash
- 反序列化后通过 `db.merge(load=False)` 绑定到当前请求的 Session
- 降级：Redis 不可用时保留现有内存字典逻辑
- `invalidate_user_cache()` → 改为 `redis.delete(f"user:{user_id}")`

**改动点**：
- `_get_cached_user()` → 先查 Redis，miss 查 DB 并写入 Redis
- `invalidate_user_cache()` → 增加 Redis DEL 操作
- 被封禁/修改资料/改密码时的所有 `invalidate_user_cache()` 调用方自动受益

---

### P0-3. 速率限制迁移

**文件**：`rate_limit.py`

**当前实现**：
```python
# 第 14 行 — 内存存储
limiter = Limiter(key_func=get_remote_address)
```

**迁移方案**（改动极小）：
```python
from .config import get_settings

settings = get_settings()

limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=settings.REDIS_URL if settings.REDIS_URL else "memory://",
)
```

slowapi 原生支持 `redis://` 作为 storage_uri，一行改动即可。

---

## 四、Phase 1 — 核心性能优化

> 预计工时：1.5 天

### P1-1. 未读通知计数器

**文件**：`routers/notifications.py`

**当前实现**（第 198-210 行）：
```python
# 每次轮询都执行 COUNT 查询
result = db.query(
    func.count(Notification.id).label("total"),
    func.count(case((Notification.is_read == False, 1))).label("unread")
).filter(Notification.user_id == current_user.id).first()
```

**迁移方案**：使用 Redis 字符串计数器 `unread:{user_id}`

| 操作 | Redis 命令 | 触发位置 |
|------|-----------|----------|
| 读取未读数 | `GET unread:{user_id}` | `get_unread_count()` |
| 新通知 +1 | `INCR unread:{user_id}` | `create_notification()` 第 53 行 |
| 标记已读 -1 | `DECR unread:{user_id}` | `mark_as_read()` 第 214 行 |
| 全部已读归零 | `SET unread:{user_id} 0` | `mark_all_as_read()` 第 241 行 |
| 首次初始化 | `GET` 返回 nil → 查 DB → `SET` | 自动触发 |

**收益**：最高频的轮询接口，延迟从 4-10ms → **0.3ms**，DB 查询从 2 次 → **0 次**。

---

### P1-2. 拉黑列表缓存

**文件**：`routers/blocks.py`

**当前实现**（第 15 行）：
```python
def get_blocked_user_ids(db: Session, user_id: int) -> set:
    # UNION ALL 查询双向拉黑关系
```

**调用方**（5 处）：`list_threads`、`get_thread`、`search_threads`、`get_trending`、`list_sub_replies`

**迁移方案**：
```python
# Redis Set: blocks:{user_id}，TTL 60 秒
async def get_blocked_user_ids(db, user_id):
    r = get_redis()
    if r:
        cached = await r.smembers(f"blocks:{user_id}")
        if cached:
            return {int(uid) for uid in cached}
    
    # DB 查询（保持原逻辑）
    ids = _query_blocked_ids_from_db(db, user_id)
    
    if r and ids:
        pipe = r.pipeline()
        pipe.sadd(f"blocks:{user_id}", *ids)
        pipe.expire(f"blocks:{user_id}", 60)
        await pipe.execute()
    
    return ids
```

**失效时机**：拉黑/取消拉黑时 `DEL blocks:{user_id}` + `DEL blocks:{target_id}`（双方都失效）

---

### P1-3. 审核配置缓存迁移

**文件**：`moderation.py`

**当前实现**（第 239-248 行）：
```python
# 进程级全局变量
_moderator_cache: Optional[ContentModerator] = None
_moderator_cache_time: float = 0
_MODERATOR_CACHE_TTL = 60
```

**迁移方案**：将 5 个审核配置项缓存到 Redis Hash `settings:moderation`，TTL 60 秒。

```python
async def _load_settings_cached(db: Session) -> dict:
    r = get_redis()
    if r:
        cached = await r.hgetall("settings:moderation")
        if cached:
            return cached
    
    # 回落到 DB（保持现有批量查询）
    settings_map = _load_settings_from_db(db)
    
    if r:
        await r.hset("settings:moderation", mapping=settings_map)
        await r.expire("settings:moderation", 60)
    
    return settings_map
```

**失效时机**：管理员修改审核配置时 `DEL settings:moderation`

---

### P1-4. 系统设置缓存层

**文件**：`settings_utils.py`

**当前实现**：每次 `get_setting()` / `get_settings_batch()` 都直接查 DB。

**迁移方案**：在现有函数内部增加 Redis 缓存层。

```python
# 策略：所有设置存入一个 Redis Hash "sys:settings"

async def get_setting(db, key, default=""):
    r = get_redis()
    if r:
        val = await r.hget("sys:settings", key)
        if val is not None:
            return val
    # 回落 DB
    val = _db_get_setting(db, key, default)
    if r:
        await r.hset("sys:settings", key, val)
        await r.expire("sys:settings", 300)
    return val

async def set_setting(db, key, value):
    _db_set_setting(db, key, value)
    r = get_redis()
    if r:
        await r.hdel("sys:settings", key)  # 失效单个 key
```

---

### P1-5. SSE 跨实例推送

**文件**：`sse.py` + `notifier.py`

**当前实现**：`SSEManager._connections` 只维护当前进程的 SSE 连接，跨实例消息不可达。

**迁移方案**：引入 Redis Pub/Sub 作为跨实例消息总线。

```
实例A 发消息 → redis.publish("sse:user:{id}", msg)
                ↓
         Redis Pub/Sub 频道
                ↓
实例B 订阅该频道 → 转发到本地 asyncio.Queue → SSE 推送给客户端
```

**具体改动**：

1. **`SSEManager.connect()`** — 连接时 `SADD sse:online {user_id}`
2. **`SSEManager.disconnect()`** — 断开且该用户无其他本地连接时 `SREM sse:online {user_id}`  
3. **`send_to_user()`** — 改为 `PUBLISH sse:user:{user_id} {json}`
4. **`broadcast()`** — 改为 `PUBLISH sse:broadcast {json}`
5. **新增后台订阅任务** — 每个实例 startup 时启动 `asyncio.Task`，订阅 `sse:*` 频道，收到消息后分发到本地 Queue
6. **`is_user_online()`** — 改为 `SISMEMBER sse:online {user_id}`
7. **`get_online_users()`** — 改为 `SMEMBERS sse:online`

**复杂度较高**，建议单独作为一个 PR 实施。

---

## 五、Phase 2 — 锦上添花

> 预计工时：1 天

### P2-1. 浏览量异步计数

**文件**：`routers/threads.py` 第 443-445 行

**当前实现**：
```python
db.query(Thread).filter(Thread.id == thread_id).update(
    {Thread.view_count: func.coalesce(Thread.view_count, 0) + 1},
    synchronize_session="fetch"
)
```

每次查看帖子详情都执行一次 DB UPDATE（含行锁）。

**迁移方案**：
```python
# 访问时只做 Redis INCR（~0.1ms，无锁）
await redis.incr(f"views:{thread_id}")

# 定时回写任务（每 60 秒或累计 100+ 次），在 main.py 注册
async def flush_view_counts():
    r = get_redis()
    keys = await r.keys("views:*")
    for key in keys:
        count = await r.getdel(key)
        if count:
            thread_id = int(key.split(":")[1])
            db.execute(
                update(Thread)
                .where(Thread.id == thread_id)
                .values(view_count=Thread.view_count + int(count))
            )
    db.commit()
```

**收益**：消除帖子详情页唯一的 DB 写操作 + 行锁竞争。

---

### P2-2. 用户等级缓存

**文件**：`level_service.py`

| 函数 | 当前 | 迁移后 |
|------|------|--------|
| `batch_get_user_levels()` | 每次 DB 查询 | Redis MGET 批量读取，TTL 30 分钟 |
| `add_exp_for_post/reply/liked()` | 写 DB | 写 DB 后更新 Redis 缓存 |

Key: `level:{user_id}` → Hash `{ level, exp }`

---

### P2-3. 热帖列表缓存

**文件**：`routers/threads.py` 第 36 行 `get_trending()`

```python
# 缓存整个热帖 JSON 结果，TTL 2-5 分钟
# Key: trending:{days}:{limit}
```

---

### P2-4. 图床每日上传计数器

**文件**：`routers/imagebed.py`

```python
# 替代每次请求的 COUNT 查询
# Key: imgbed:daily:{user_id}:{YYYY-MM-DD}，TTL 86400
await redis.incr(f"imgbed:daily:{user_id}:{today}")
```

---

### P2-5. 管理后台统计缓存

**文件**：`routers/admin.py` — `get_stats()`

缓存 4 个 COUNT 查询结果，TTL 30 秒。

---

## 六、文件改动清单

### 新增文件

| 文件 | 说明 |
|------|------|
| `server/app/redis_client.py` | Redis 连接池管理（~50 行） |

### 修改文件

| 文件 | Phase | 改动量 | 说明 |
|------|:-----:|:------:|------|
| `requirements.txt` | 基础 | +1 行 | 添加 `redis[hiredis]>=5.0.0` |
| `config.py` | 基础 | +1 行 | 添加 `REDIS_URL` |
| `main.py` | 基础 | ~10 行 | startup/shutdown 生命周期 + 浏览量定时回写任务 |
| `rate_limit.py` | P0 | ~3 行 | `storage_uri` 改为 Redis |
| `routers/oauth.py` | P0 | ~30 行 | `_oauth_states` → Redis + 修复 bug |
| `auth.py` | P0 | ~40 行 | `_user_cache` → Redis，增加序列化逻辑 |
| `routers/notifications.py` | P1 | ~25 行 | 未读计数 → Redis INCR/DECR |
| `routers/blocks.py` | P1 | ~20 行 | 拉黑列表 → Redis Set |
| `moderation.py` | P1 | ~20 行 | 审核配置缓存 → Redis Hash |
| `settings_utils.py` | P1 | ~25 行 | 通用设置缓存层 |
| `sse.py` | P1 | ~80 行 | 在线状态 + Pub/Sub 消息总线（最大改动） |
| `notifier.py` | P1 | ~10 行 | 跟随 SSE 适配 |
| `routers/threads.py` | P2 | ~30 行 | 浏览量 INCR + 热帖缓存 |
| `level_service.py` | P2 | ~25 行 | 等级缓存读写 |
| `routers/imagebed.py` | P2 | ~10 行 | 每日上传计数器 |
| `routers/admin.py` | P2 | ~15 行 | 统计缓存 + 配置失效 |

**总计新增/修改**：约 **350-400 行**代码（含降级逻辑）。

### 无需改动

| 文件 | 原因 |
|------|------|
| `models.py` | 纯 ORM 定义，无缓存逻辑 |
| `schemas.py` | 纯 Pydantic 模型 |
| `serializers.py` | 序列化工具 |
| `database.py` | DB 连接管理，不涉及 |
| `routers/upload.py` | 本地文件上传，不涉及 |
| `routers/auth.py`（路由） | 调用 `auth.py` 核心模块，自动受益 |
| `routers/likes.py` | P2 可选优化，核心流程不影响 |

---

## 七、Redis Key 规范总表

所有 Key 遵循 `{模块}:{实体}:{id}` 命名规范：

| Key 模式 | 类型 | TTL | Phase | 用途 |
|----------|------|-----|:-----:|------|
| `oauth:state:{token}` | String (JSON) | 600s | P0 | OAuth CSRF state |
| `user:{user_id}` | String (JSON) | 300s | P0 | 用户认证缓存 |
| `unread:{user_id}` | String (int) | ∞ | P1 | 未读通知计数器 |
| `blocks:{user_id}` | Set | 60s | P1 | 双向拉黑 ID 集合 |
| `settings:moderation` | Hash | 60s | P1 | 审核配置 |
| `sys:settings` | Hash | 300s | P1 | 系统设置 |
| `sse:online` | Set | ∞ | P1 | SSE 在线用户 ID |
| `sse:user:{user_id}` | Pub/Sub Channel | - | P1 | 定向推送频道 |
| `sse:broadcast` | Pub/Sub Channel | - | P1 | 全局广播频道 |
| `views:{thread_id}` | String (int) | ∞* | P2 | 浏览量计数器（定时回写后删除） |
| `level:{user_id}` | Hash | 1800s | P2 | 用户等级 & 经验 |
| `trending:{days}:{limit}` | String (JSON) | 120-300s | P2 | 热帖列表缓存 |
| `imgbed:daily:{uid}:{date}` | String (int) | 86400s | P2 | 每日上传次数 |
| `stats:dashboard` | String (JSON) | 30s | P2 | 后台统计数据 |

预计峰值内存占用：< **50 MB**（1万用户规模）。

---

## 八、风险与降级策略

### 核心原则

**Redis 是可选加速层，不是必需依赖。** 所有 Redis 操作都用 `try/except` 包裹，失败时静默降级。

### 降级矩阵

| 场景 | 降级行为 |
|------|----------|
| `REDIS_URL` 未配置 | 完全不初始化 Redis，保持现有行为 |
| Redis 连接失败 | `get_redis()` 返回 `None`，所有缓存函数走 DB |
| Redis 运行中宕机 | 每次操作 `try/except`，自动回落 DB |
| 缓存数据不一致 | 写操作时主动 DEL（不等 TTL），最终一致 |

### 具体风险

| 风险 | 概率 | 影响 | 应对 |
|------|------|------|------|
| 缓存穿透（不存在的 ID） | 中 | 无效请求打穿 DB | 缓存空值，TTL 60s |
| 缓存雪崩（大量 Key 同时过期） | 低 | 瞬时 DB 压力 | TTL 加随机偏移 ±10% |
| 未读计数漂移（极端并发） | 低 | 计数不准 | 定期从 DB 校准（可选 cron） |
| `auth.py` 序列化遗漏字段 | 中 | 业务逻辑缺数据 | 明确定义缓存字段白名单 |

---

## 九、测试计划

### 9.1 单元测试

| 场景 | 测试项 |
|------|--------|
| Redis 可用 | 缓存命中/未命中/失效 |
| Redis 不可用 | 降级到 DB 直查，无异常抛出 |
| Redis 运行中断开 | 操作失败后自动降级 |
| OAuth state | 写入 → 取出 → 过期 → 取不到 |
| 未读计数 | INCR → GET → DECR → 归零 |

### 9.2 集成测试

| 场景 | 验证 |
|------|------|
| 多实例 OAuth 流程 | 实例 A 发起 → 实例 B 回调成功 |
| 多实例 SSE 推送 | 用户连在实例 A → 实例 B 触发通知 → 用户收到 |
| 封禁用户 | 管理员封禁 → 用户缓存立即失效 → 下次请求被拒 |
| 速率限制 | 多实例共享计数器，总数不超限 |

### 9.3 压力测试

- 对比 Redis 前后的 p50/p95/p99 延迟
- 验证 Redis 宕机后系统仍正常工作（延迟退化可接受）

---

## 十、预期收益

### 延迟对比

```
                    当前 (无 Redis)      + Phase 0+1         + Phase 2
                    ────────────         ──────────          ──────────
帖子列表延迟         ~18-30ms            ~7-11ms             ~7-11ms
帖子详情延迟         ~15-25ms            ~10-17ms            ~8-14ms
未读数轮询           ~4-10ms             ~0.3ms              ~0.3ms
DB 查询/请求         4-6 次              1-3 次              1-2 次
```

### DB 查询次数对比

| 接口 | 当前 | + P0+P1 | + P2 |
|------|:----:|:-------:|:----:|
| `GET /threads` | 6 | 2 | 2 |
| `GET /threads/{id}` | 5+1写 | 3 | 2 (无写) |
| `GET /unread-count` | 2 | **0** | 0 |
| `GET /notifications` | 3 | 1-2 | 1-2 |
| `POST /replies` | 8-9 | 5-6 | 5-6 |
| `POST /like` | 8 | 4-5 | 4-5 |
| `GET /sub_replies` | 5 | 2-3 | 2-3 |

### 部署能力

| 维度 | 当前 | 迁移后 |
|------|------|--------|
| 实例数 | 仅 1 | 多实例水平扩展 |
| PG QPS 上限 | ~800 | ~2000+ |
| SSE 跨实例 | 不可用 | 完全可用 |
| 限流跨实例 | 不生效 | 全局生效 |

---

## 附录：实施顺序建议

```
Week 1:
  ├─ Day 1: 基础设施 + P0 全部（redis_client.py, config, rate_limit, oauth, auth）
  ├─ Day 2: P1-1~P1-4（notifications, blocks, moderation, settings_utils）
  └─ Day 3: P1-5（SSE Pub/Sub，最复杂，单独实施）

Week 2:
  ├─ Day 4: P2 全部（threads, level, imagebed, admin）
  └─ Day 5: 集成测试 + 压力测试 + 文档更新
```

每个 Phase 完成后可独立部署验证，不必等全部完成。
