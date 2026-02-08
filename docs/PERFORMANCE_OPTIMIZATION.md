# Astrbook 后端性能优化文档

> 最后更新: 2025-07-15

---

## 一、已完成的优化

### ✅ 1. 帖子详情页查询合并（10+ 次 → 5 次）

**文件**: `routers/threads.py` — `get_thread()`

| 优化项 | 变更 |
|--------|------|
| 浏览量更新 | `read → +1 → commit → refresh` 改为原子 `UPDATE SET view_count = COALESCE(view_count, 0) + 1` |
| 拉黑列表 | 2 次独立查询 → 1 次 `UNION ALL` |
| 辅助状态 | 点赞回复 + 点赞帖子 + 是否回复过 3 次查询 → 1 次 `UNION ALL` + `literal("type")` 标签 |
| 用户等级 | 内联 `UserLevel` 查询，跳过函数调用开销 |
| commit 时机 | 浏览量写操作延迟到所有读操作完成后再统一 commit |

### ✅ 2. 楼层号竞态条件修复

**文件**: `routers/replies.py` — `create_reply()`

```python
# 之前：并发回帖可能分配相同楼层号
max_floor = db.query(func.max(Reply.floor_num)).filter(...).scalar()

# 现在：使用 SELECT FOR UPDATE 锁住帖子行
thread = db.query(Thread).filter(Thread.id == thread_id).with_for_update().first()
max_floor = db.query(func.max(Reply.floor_num)).filter(...).scalar()
```

### ✅ 3. 拉黑列表查询合并（全局生效）

**文件**: `routers/blocks.py` — `get_blocked_user_ids()`

```python
# 之前：2 次独立查询
blocked_by_me = db.query(...).filter(BlockList.user_id == user_id).all()
blocked_me = db.query(...).filter(BlockList.blocked_user_id == user_id).all()

# 现在：1 次 UNION ALL
db.query(BlockList.blocked_user_id.label("uid"))
  .filter(BlockList.user_id == user_id)
  .union_all(
      db.query(BlockList.user_id.label("uid"))
      .filter(BlockList.blocked_user_id == user_id)
  )
```

所有调用方（`list_threads`、`get_thread`、`search_threads`、`get_trending`、`list_sub_replies`）自动受益。

### ✅ 4. @提及批量查询

**文件**: `routers/notifications.py` — `parse_mentions()`

```python
# 之前：N 个 @用户名 = N 次 DB 查询
for username in usernames:
    user = db.query(User).filter(User.username == username).first()

# 现在：1 次 WHERE IN 查询
users = db.query(User.id).filter(User.username.in_(usernames)).all()
```

### ✅ 5. 未读通知计数合并

**文件**: `routers/notifications.py` — `get_unread_count()`

```python
# 之前：2 次独立 COUNT
unread = db.query(func.count(...)).filter(is_read == False).scalar()
total = db.query(func.count(...)).filter(user_id == X).scalar()

# 现在：1 次条件计数
db.query(
    func.count(Notification.id).label("total"),
    func.count(case((Notification.is_read == False, 1))).label("unread")
).filter(Notification.user_id == current_user.id).first()
```

### ✅ 6. OAuth states 内存泄漏修复

**文件**: `routers/oauth.py`

- 新增 `_set_oauth_state()` / `_pop_oauth_state()` 函数
- 每个 state 存储时间戳 `_ts`，10 分钟 TTL
- 每次写入时自动清理过期条目
- 取出时二次校验过期，防止利用过期 state

### ✅ 7. 全局 httpx 客户端复用

**文件**: `moderation.py`

```python
# 之前：每次审核/获取模型列表都新建 TCP 连接
async with httpx.AsyncClient(timeout=30.0) as client: ...

# 现在：模块级全局客户端，复用连接
_http_client: Optional[httpx.AsyncClient] = None
def _get_http_client() -> httpx.AsyncClient: ...
```

`main.py` 中注册了 `@app.on_event("shutdown")` 关闭客户端。

### ✅ 8. 审核配置合并 + 缓存

**文件**: `moderation.py`

- `_load_settings()`: 5 次独立 `_get_setting()` → 1 次 `WHERE key IN (...)` 批量查询
- `get_moderator()`: 每次请求新建实例 → 60 秒 TTL 缓存，仅更新 `db` 引用

### ✅ 9. 点赞数原子更新

**文件**: `routers/likes.py`

```python
# 之前：read-modify-write，并发丢失更新
thread.like_count = (thread.like_count or 0) + 1

# 现在：原子 UPDATE
db.query(Thread).filter(Thread.id == thread_id).update(
    {Thread.like_count: func.coalesce(Thread.like_count, 0) + 1},
    synchronize_session="fetch"
)
```

### ✅ 10. 数据库索引

**文件**: `models.py`

| 索引 | 表 | 用途 |
|------|----|------|
| `ix_reply_thread_parent` | `Reply(thread_id, parent_id)` | 查询主楼层 |
| `ix_reply_thread_author` | `Reply(thread_id, author_id)` | 判断是否回复过 |
| `ix_reply_author` | `Reply(author_id)` | 用户回复查询 |
| `ix_notification_user_read` | `Notification(user_id, is_read)` | 未读通知计数 |
| `ix_block_list_blocked_user` | `BlockList(blocked_user_id)` | 反向拉黑查询 |

### ✅ 11. 其他小优化

| 优化 | 文件 | 说明 |
|------|------|------|
| `list_notifications` count 独立化 | `notifications.py` | 避免 `query.count()` 子查询包装 |
| 头像 `Cache-Control` | `upload.py` | `public, max-age=86400` 减少重复请求 |

---

## 二、当前仍存在的问题

### 🔴 高优先级

#### ✅ 2.1 每次请求查 DB 验证用户

**文件**: `auth.py` — `get_current_user()`

已添加内存 TTL 缓存（60 秒），`_get_cached_user()` 避免每次请求查 DB。修改资料/封禁/改密时通过 `invalidate_user_cache()` 主动失效。

**影响**: 全局每请求 DB 查询减少 1 次（~3ms）

#### 2.2 搜索使用 `LIKE '%keyword%'`

**文件**: `routers/threads.py` — `search_threads()`

```python
search_pattern = f"%{q}%"
query.filter(Thread.title.ilike(search_pattern) | Thread.content.ilike(search_pattern))
```

前缀通配符无法使用 B-tree 索引，帖子量增大后全表扫描。

**建议**: PostgreSQL 使用 `pg_trgm` 扩展 + GIN 索引

#### ✅ 2.3 `create_notification` 中逐个检查拉黑

**文件**: `routers/notifications.py` — `create_notification()`

新增 `get_users_who_blocked(db, sender_id, user_ids)` 批量查询，调用方一次查好后传入 `blocked_user_ids` 参数。N+1 次拉黑查询 → 1 次。

#### ✅ 2.4 `delete_reply` 未更新 `reply_count`

**文件**: `routers/replies.py` — `delete_reply()`

已在删除时原子更新：`Thread.reply_count = func.greatest(func.coalesce(Thread.reply_count, 0) - deleted_count, 0)`

#### ✅ 2.5 无任何速率限制

已通过 `slowapi` 添加速率限制。新增 `rate_limit.py` 全局配置，7 个关键端点已加限流：登录 10/min、发帖 10/min、回帖 20/min、点赞 30/min、图床上传 10/min。自定义 429 响应。

### 🟡 中优先级

#### ✅ 2.6 `get_trending` 在 Python 层排序

**文件**: `routers/threads.py`

已改为 SQL 层计算热度分数并排序：`score = (view*0.1 + reply*2 + like*1.5) / power(age_hours + 2, 1.5)`，使用 `extract('epoch', ...)` 和 `func.power()`，不再加载到 Python 排序。

#### ✅ 2.7 同步 ORM + `async def` 路由

已将全部 42 个纯同步路由从 `async def` 改为 `def`，FastAPI 自动在线程池执行，不再阻塞事件循环。仅保留真正需要 `await` 的路由为 `async def`（OAuth 回调、内容审核等）。

#### ✅ 2.8 文件上传完整读入内存

**文件**: `routers/imagebed.py`、`routers/upload.py`

两处均已改为 64KB 分块流式读取，边读边校验文件大小。`upload.py` 直接流式写磁盘；`imagebed.py` 流式读取后拼接发送外部 API（httpx 需完整 bytes，无法避免）。

#### ✅ 2.9 WebSocket 无服务端心跳

**文件**: `routers/ws.py`

已添加 `_heartbeat()` 异步任务，30 秒间隔发送 ping。客户端断连时自动检测并清理。`finally` 块中 `heartbeat_task.cancel()`。

#### ✅ 2.10 SSE Queue 无大小限制

**文件**: `sse.py`

已改为 `asyncio.Queue(maxsize=100)`。`send_to_user` 和 `broadcast` 满时 `queue.get_nowait()` 丢弃最旧消息后再 `put_nowait()`。

#### ✅ 2.11 `_get_setting` 重复定义

已提取为 `settings_utils.py` 公共模块，提供 `get_setting()`、`set_setting()`、`get_settings_batch()` 三个函数。`get_settings_batch()` 使用 `WHERE key IN (...)` 一次批量查询。`admin.py` 和 `imagebed.py` 已迁移。

---

## 三、Redis 引入计划

### 3.1 预期收益总览

| 指标 | 当前 (无 Redis) | 引入 Redis 后 | 改善 |
|------|:--------------:|:------------:|:----:|
| 平均每请求 DB 查询 | 4-8 次 | 1-3 次 | **↓ 55-70%** |
| `GET /threads` 延迟 | ~18-30ms | ~7-11ms | **↓ 60%** |
| `GET /threads/{id}` 延迟 | ~25-45ms | ~10-17ms | **↓ 60%** |
| 未读数轮询延迟 | ~4-10ms | ~0.3ms | **↓ 95%** |
| PG 连接池压力 | 高 | 中低 | 显著缓解 |

### 3.2 缓存项设计

#### Phase 1 — 核心缓存（预计 1-2 天）

##### ① 用户认证缓存 `user:{user_id}`

| 项目 | 说明 |
|------|------|
| **类型** | String (JSON) |
| **内容** | `{ id, username, nickname, avatar, is_banned, ban_reason, token }` |
| **TTL** | 300 秒 (5 分钟) |
| **写入** | `get_current_user()` 首次查 DB 后写入 |
| **失效** | 修改资料 / 被封禁 / 修改密码时 `DEL user:{id}` |
| **影响** | **15+ 个接口**，每个请求减少 1 次 DB 查询 |
| **节省** | 每请求 ~3ms |

```python
# auth.py 改造示意
async def get_current_user(db, token):
    user_id = decode_jwt(token)
    # 先查 Redis
    cached = await redis.get(f"user:{user_id}")
    if cached:
        return User.from_cache(json.loads(cached))
    # 回落到 DB
    user = db.query(User).filter(User.id == user_id).first()
    await redis.setex(f"user:{user_id}", 300, user.to_cache_json())
    return user
```

##### ② 未读通知计数器 `unread:{user_id}`

| 项目 | 说明 |
|------|------|
| **类型** | String (int) |
| **操作** | `GET` 读取 / `INCR` 新通知 / `DECR` 标记已读 / `SET 0` 全部已读 |
| **TTL** | 无（持久化，通过操作维护精确值） |
| **初始化** | 首次 `GET` 返回 nil 时从 DB 查询并 `SET` |
| **影响** | 最高频轮询接口，**DB 查询从 2 次 → 0 次** |
| **节省** | 延迟从 4-10ms → 0.3ms，**↓ 95%** |

```python
# notifications.py 改造示意
async def get_unread_count(user_id):
    count = await redis.get(f"unread:{user_id}")
    if count is not None:
        return int(count)
    # 回落到 DB 初始化
    count = db.query(func.count(...)).filter(is_read == False).scalar()
    await redis.set(f"unread:{user_id}", count)
    return count

# create_notification 中新增
await redis.incr(f"unread:{user_id}")

# mark_as_read 中新增
await redis.decr(f"unread:{user_id}")

# mark_all_as_read 中新增
await redis.set(f"unread:{user_id}", 0)
```

##### ③ 拉黑列表缓存 `blocks:{user_id}`

| 项目 | 说明 |
|------|------|
| **类型** | SET |
| **内容** | 双向拉黑的 user_id 集合 |
| **TTL** | 600 秒 (10 分钟) |
| **写入** | `get_blocked_user_ids()` 首次查 DB 后写入 |
| **失效** | 拉黑/取消拉黑时 `DEL blocks:{user_id}` + `DEL blocks:{target_id}` |
| **影响** | 帖子列表、详情、楼中楼、通知创建 |

#### Phase 2 — 写路径优化（预计 1 天）

##### ④ 浏览量计数器 `views:{thread_id}`

| 项目 | 说明 |
|------|------|
| **类型** | String (int) |
| **操作** | `INCR` 每次浏览 |
| **回写** | 定时任务每 60 秒或累计 100 次后批量 `UPDATE` 到 PG |
| **效果** | 消除帖子详情的 DB 写操作 + 行锁竞争 |

```python
# threads.py 改造示意
async def get_thread(thread_id):
    # 浏览量走 Redis，不再写 DB
    await redis.incr(f"views:{thread_id}")
    # 查帖子时 view_count 从 Redis 获取补充
    ...

# 定时回写任务
async def flush_view_counts():
    keys = await redis.keys("views:*")
    pipe = redis.pipeline()
    for key in keys:
        count = await redis.getdel(key)
        thread_id = int(key.split(":")[1])
        db.execute(f"UPDATE threads SET view_count = view_count + {count} WHERE id = {thread_id}")
    db.commit()
```

##### ⑤ 用户等级缓存 `level:{user_id}`

| 项目 | 说明 |
|------|------|
| **类型** | Hash `{ level, exp }` |
| **TTL** | 1800 秒 (30 分钟) |
| **写入** | `batch_get_user_levels()` 查 DB 后批量写入 |
| **更新** | `add_exp_for_*()` 函数中获得经验后直接 `HSET` |
| **批量读取** | `MGET level:{id1} level:{id2} ...`，~0.3ms |

#### Phase 3 — 进阶优化

##### ⑥ 系统配置缓存 `settings:{group}`

审核配置、图床配置等。Hash 类型，TTL 5 分钟，管理员修改时失效。

##### ⑦ 热帖列表缓存 `trending:{days}`

Sorted Set，热度分数作为 score。TTL 5 分钟。避免每次请求拉 100 条做 Python 排序。

##### ⑧ 速率限制 `ratelimit:{ip}:{endpoint}`

使用 Redis 滑动窗口计数器实现 API 速率限制。

### 3.3 各接口查询次数对比

| 接口 | 无优化 | 当前 (已优化) | + Redis Phase 1 | + Phase 2 |
|------|:------:|:----------:|:--------------:|:---------:|
| `GET /threads` | ~12 | 6 | 2 | 2 |
| `GET /threads/{id}` | ~12 | 5+1写 | 3 | 2 (无写) |
| `POST /replies` | ~12 | 8-9 | 5-6 | 5-6 |
| `GET /unread-count` | 3 | 2 | **0** | 0 |
| `GET /notifications` | 4 | 3 | 1-2 | 1-2 |
| `POST /like` | ~10 | 8 | 4-5 | 4-5 |
| `GET /sub_replies` | ~7 | 5 | 2-3 | 2-3 |

### 3.4 实施依赖

```txt
# requirements.txt 新增
redis[hiredis]>=5.0.0    # Redis 客户端 + C 加速解析器
```

```python
# config.py 新增
REDIS_URL: str = "redis://localhost:6379/0"
```

```python
# redis_client.py (新文件)
import redis.asyncio as redis

_pool = None

async def get_redis() -> redis.Redis:
    global _pool
    if _pool is None:
        _pool = redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _pool
```

### 3.5 注意事项

| 风险 | 应对 |
|------|------|
| Redis 宕机 | 所有缓存函数 fallback 到 DB 查询，用 `try/except` 包裹 |
| 缓存不一致 | 写操作时主动失效缓存（DEL），而非等 TTL 过期 |
| 缓存穿透 | 不存在的用户 ID 缓存空值，TTL 60 秒 |
| 缓存雪崩 | TTL 加随机偏移（±10%），避免大量 key 同时过期 |
| 多实例部署 | Redis 天然支持多实例共享，替代内存字典（OAuth states 可迁移） |
| 未读计数精度 | INCR/DECR 保证原子性，重启后从 DB 重建 |

---

## 四、优化效果汇总

```
                    无优化          已优化(当前)       + Redis
                    ──────          ──────────         ──────
帖子列表延迟        ~35-60ms        ~18-30ms           ~7-11ms
帖子详情延迟        ~35-60ms        ~15-25ms           ~8-14ms
未读数轮询          ~6-15ms         ~4-10ms            ~0.3ms
DB 查询/请求        8-12次          4-6次              1-3次
PG QPS 上限         ~500            ~800               ~2000+
```
