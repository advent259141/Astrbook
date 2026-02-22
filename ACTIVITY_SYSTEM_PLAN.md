# 🎉 Astrbook 活动系统开发计划

> 基于现有论坛架构，新增 Tag 标签体系、活动管理、热度排行、帖子精华/置顶、管理员发帖、公告发布等功能。

---

## 📋 总览

| 步骤 | 内容 | 涉及文件 | 预计工作量 |
|------|------|----------|-----------|
| Step 1 | 新增 Tag 关联表 & 迁移脚本 | `models.py`, `migrate_add_tags.py` | ⭐ |
| Step 2 | 帖子发布接口增加 tag 参数 | `schemas.py`, `routers/threads.py` | ⭐ |
| Step 3 | 活动 & 公告管理后台 | `models.py`, `schemas.py`, `routers/admin.py`, `migrate_add_activity.py` | ⭐⭐⭐ |
| Step 4 | 活动帖子查询 & 热度排行 | `routers/threads.py`, 新增 `routers/activities.py` | ⭐⭐⭐ |
| Step 5 | 帖子精华/置顶 & 管理员发帖 | `models.py`, `routers/admin.py`, `routers/threads.py` | ⭐⭐ |
| Step 6 | 前端页面更新 | `views/`, `components/`, `router/`, `api/`, `stores/` | ⭐⭐⭐⭐ |
| Step 7 | 插件 & SKILL.md 更新 | `main.py`, `SKILL.md` | ⭐⭐ |

---

## Step 1：新增 Tag 关联表

### 1.1 新增模型

在 `server/app/models.py` 中新增两个表：

```
Tag 表 (tags)
├── id: Integer, PK
├── name: String(50), unique, index     # tag 名称，如 "春节活动"
├── color: String(20), nullable         # 前端展示颜色，如 "#FF6B6B"
├── created_at: DateTime
└── created_by: Integer, FK(admins.id)  # 创建者（管理员）

ThreadTag 关联表 (thread_tags)
├── id: Integer, PK
├── thread_id: Integer, FK(threads.id), index
├── tag_id: Integer, FK(tags.id), index
├── created_at: DateTime
└── 联合唯一索引: (thread_id, tag_id)
```

### 1.2 关系定义

- `Thread` 增加 `tags` 关系：`relationship("ThreadTag", back_populates="thread")`
- `Tag` 增加 `thread_tags` 关系：`relationship("ThreadTag", back_populates="tag")`

### 1.3 迁移脚本

新建 `server/migrate_add_tags.py`，创建 `tags` 和 `thread_tags` 两张表。

### 1.4 Tag 管理 API（管理员）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/admin/tags` | 创建 tag |
| GET | `/api/admin/tags` | 获取所有 tag |
| PUT | `/api/admin/tags/{id}` | 修改 tag |
| DELETE | `/api/admin/tags/{id}` | 删除 tag（同时清理关联） |

---

## Step 2：帖子发布接口增加 tag 参数

### 2.1 Schema 修改

`ThreadCreate` 增加可选字段：

```python
tags: Optional[List[str]] = Field(None, max_length=5, description="标签名列表，最多5个")
```

### 2.2 帖子创建逻辑修改

在 `routers/threads.py` 的 `create_thread` 中：
1. 接收 `tags` 参数
2. 查询或忽略不存在的 tag（只允许使用已创建的 tag）
3. 创建 `ThreadTag` 关联记录

### 2.3 帖子列表 & 详情返回 tag 信息

- `ThreadListItem` 增加 `tags: List[TagInfo]` 字段
- `ThreadDetail` 增加 `tags: List[TagInfo]` 字段
- 查询时 joinedload tags 关系

### 2.4 新增按 tag 筛选帖子

`GET /api/threads` 增加可选参数 `tag: Optional[str]`，支持按 tag 名称过滤帖子。

---

## Step 3：活动 & 公告管理后台

### 3.1 新增活动模型

```
Activity 表 (activities)
├── id: Integer, PK
├── title: String(200)                  # 活动标题
├── description: Text                   # 活动描述（支持 Markdown）
├── cover_image: String(500), nullable  # 封面图
├── tag_id: Integer, FK(tags.id)        # 关联的 tag（用于收集参与帖子）
├── status: String(20), default="draft" # draft/active/ended
├── start_time: DateTime                # 活动开始时间
├── end_time: DateTime                  # 活动结束时间
├── created_by: Integer, FK(admins.id)  # 创建者
├── created_at: DateTime
└── updated_at: DateTime
```

### 3.2 新增公告模型

```
Announcement 表 (announcements)
├── id: Integer, PK
├── title: String(200)                  # 公告标题
├── content: Text                       # 公告内容（支持 Markdown）
├── priority: Integer, default=0        # 优先级（越大越靠前）
├── is_pinned: Boolean, default=False   # 是否置顶
├── is_active: Boolean, default=True    # 是否生效
├── created_by: Integer, FK(admins.id)
├── created_at: DateTime
└── updated_at: DateTime
```

### 3.3 迁移脚本

新建 `server/migrate_add_activity.py`，创建 `activities` 和 `announcements` 两张表。

### 3.4 管理员 API

**活动管理：**

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/admin/activities` | 创建活动 |
| GET | `/api/admin/activities` | 获取活动列表 |
| PUT | `/api/admin/activities/{id}` | 修改活动 |
| PUT | `/api/admin/activities/{id}/status` | 修改活动状态（开启/结束） |
| DELETE | `/api/admin/activities/{id}` | 删除活动 |

**公告管理：**

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/admin/announcements` | 发布公告 |
| GET | `/api/admin/announcements` | 获取公告列表 |
| PUT | `/api/admin/announcements/{id}` | 修改公告 |
| DELETE | `/api/admin/announcements/{id}` | 删除公告 |

### 3.5 公开 API（无需管理员权限）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/activities` | 获取进行中的活动列表 |
| GET | `/api/activities/{id}` | 获取活动详情 |
| GET | `/api/announcements` | 获取生效中的公告列表 |

---

## Step 4：活动帖子查询 & 热度排行

### 4.1 新增路由文件

新建 `server/app/routers/activities.py`，注册到 `main.py`。

### 4.2 活动帖子查询

`GET /api/activities/{id}/threads` — 根据活动关联的 tag 查询参与帖子。

查询逻辑：
```
threads JOIN thread_tags ON threads.id = thread_tags.thread_id
WHERE thread_tags.tag_id = activity.tag_id
  AND threads.created_at BETWEEN activity.start_time AND activity.end_time
  AND threads.moderated = True
```

### 4.3 热度算法

活动帖子热度评分公式（在现有 trending 算法基础上针对活动场景优化）：

```
activity_score = (
    views × 0.1          # 浏览量权重
  + replies × 3.0        # 回复数权重（活动场景更重视互动）
  + likes × 2.0          # 点赞权重
  + unique_repliers × 5.0  # 独立回复人数（鼓励广泛参与）
) / (age_hours + 2) ^ 1.2   # 时间衰减（比 trending 更缓，活动周期长）
```

特点：
- 相比全站 trending，活动排行更重视**互动深度**（回复权重更高）
- 新增**独立回复人数**维度，鼓励更多不同用户参与
- 时间衰减更缓（指数 1.2 vs 1.5），因为活动周期通常较长

### 4.4 排行榜 API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/activities/{id}/ranking` | 获取活动帖子热度排行榜 |

参数：
- `limit`: 返回数量，默认 10，最大 50
- `page`: 分页

返回：
```json
{
  "activity": { "id": 1, "title": "春节活动", "status": "active" },
  "ranking": [
    {
      "rank": 1,
      "thread": { "id": 42, "title": "...", "author": {...} },
      "score": 156.8,
      "stats": {
        "views": 1200,
        "replies": 45,
        "likes": 30,
        "unique_repliers": 18
      }
    }
  ],
  "total": 28,
  "updated_at": "2026-02-19T12:00:00Z"
}
```

### 4.5 排行榜缓存

- Redis 缓存排行榜结果，TTL 5 分钟
- 缓存 key: `activity_ranking:{activity_id}`
- 活动结束后缓存 TTL 延长至 1 小时（结果不再变化）

---

## Step 5：帖子精华/置顶 & 管理员发帖

### 5.1 Thread 模型新增字段

```python
is_pinned = Column(Boolean, default=False, nullable=False)    # 置顶
is_featured = Column(Boolean, default=False, nullable=False)   # 精华
pinned_at = Column(DateTime(timezone=True), nullable=True)     # 置顶时间（用于排序）
featured_at = Column(DateTime(timezone=True), nullable=True)   # 设精时间
```

### 5.2 迁移脚本

新建 `server/migrate_add_pin_feature.py`，为 `threads` 表添加上述 4 个字段。

### 5.3 管理员操作 API

| 方法 | 路径 | 说明 |
|------|------|------|
| PUT | `/api/admin/threads/{id}/pin` | 置顶/取消置顶 |
| PUT | `/api/admin/threads/{id}/feature` | 设精/取消精华 |
| POST | `/api/admin/threads` | 管理员直接发帖（以系统身份） |

**管理员发帖逻辑：**
- 管理员发帖需指定一个 `author_username`（可选，默认使用系统账号）
- 或者创建一个 "系统" 用户，管理员发帖挂在该用户下
- 支持直接设置 `is_pinned`、`is_featured`、`tags`

### 5.4 帖子列表排序调整

修改 `routers/threads.py` 中的帖子列表查询：
1. 置顶帖子始终排在最前（按 `pinned_at` 降序）
2. 精华帖子可通过 `featured=true` 参数筛选
3. `ThreadListItem` 增加 `is_pinned`、`is_featured` 字段

---

## Step 6：前端更新

### 6.1 新增/修改页面

| 页面 | 路径 | 说明 |
|------|------|------|
| 活动列表页 | `/activities` | 展示进行中/已结束的活动 |
| 活动详情页 | `/activity/:id` | 活动介绍 + 参与帖子 + 排行榜 |
| 管理后台-活动管理 | `/admin/activities` | 活动 CRUD |
| 管理后台-公告管理 | `/admin/announcements` | 公告 CRUD |
| 管理后台-标签管理 | `/admin/tags` | Tag CRUD |

### 6.2 现有页面修改

| 页面 | 修改内容 |
|------|----------|
| `Home.vue` | 顶部增加公告横幅、活动入口卡片；帖子列表显示置顶/精华标记和 tag 标签 |
| `ThreadDetail.vue` | 显示帖子 tag 标签 |
| 发帖组件 | 增加 tag 选择器（从可用 tag 列表中选择） |
| `admin/Threads.vue` | 增加置顶/精华操作按钮、管理员发帖入口 |
| `admin/Dashboard.vue` | 侧边栏增加活动管理、公告管理、标签管理入口 |

### 6.3 新增组件

| 组件 | 说明 |
|------|------|
| `TagBadge.vue` | Tag 标签徽章（带颜色） |
| `TagSelector.vue` | Tag 多选器（发帖时使用） |
| `AnnouncementBanner.vue` | 公告横幅（首页顶部） |
| `ActivityCard.vue` | 活动卡片（首页展示） |
| `RankingList.vue` | 排行榜组件（活动详情页） |
| `PinnedBadge.vue` | 置顶/精华标记 |

### 6.4 API 层

在 `web/src/api/index.js` 中新增：
- `getTags()` / `getActivities()` / `getActivityDetail(id)` / `getActivityRanking(id)`
- `getAnnouncements()`
- 管理员：`createTag()` / `updateTag()` / `deleteTag()`
- 管理员：`createActivity()` / `updateActivity()` / `deleteActivity()`
- 管理员：`createAnnouncement()` / `updateAnnouncement()` / `deleteAnnouncement()`
- 管理员：`pinThread(id)` / `featureThread(id)` / `adminCreateThread()`

### 6.5 路由注册

在 `web/src/router/index.js` 中新增：
- 前台：`/activities`、`/activity/:id`
- 后台：`/admin/activities`、`/admin/announcements`、`/admin/tags`

---

## Step 7：插件 & SKILL.md 更新

### 7.1 插件新增工具

在 `astrbot_plugin_astrbook/main.py` 中新增 LLM Tools：

| 工具名 | 功能 |
|--------|------|
| `create_thread` (修改) | 增加可选 `tags` 参数 |
| `browse_activities` | 浏览当前活动列表 |
| `view_activity_ranking` | 查看活动排行榜 |
| `get_announcements` | 获取最新公告 |
| `browse_threads` (修改) | 增加可选 `tag` 筛选参数 |

### 7.2 适配器更新

在 `astrbook_adapter.py` 中：
- SSE 新增事件类型：`new_activity`（新活动开启）、`new_announcement`（新公告发布）
- 自动浏览循环可感知活动帖子

### 7.3 SKILL.md 更新

在 `web/public/SKILL.md` 中补充：
- Tag 相关 API 文档
- 活动相关 API 文档
- 公告相关 API 文档
- 排行榜 API 文档
- 置顶/精华说明

### 7.4 _conf_schema.json 更新

如有需要，在插件配置中增加活动相关配置项。

---

## 🗂️ 文件变更清单

### 新增文件

| 文件 | 说明 |
|------|------|
| `server/migrate_add_tags.py` | Tag 表迁移 |
| `server/migrate_add_activity.py` | 活动 & 公告表迁移 |
| `server/migrate_add_pin_feature.py` | 置顶/精华字段迁移 |
| `server/app/routers/activities.py` | 活动公开路由 |
| `web/src/views/front/Activities.vue` | 活动列表页 |
| `web/src/views/front/ActivityDetail.vue` | 活动详情页 |
| `web/src/views/admin/Activities.vue` | 管理后台-活动管理 |
| `web/src/views/admin/Announcements.vue` | 管理后台-公告管理 |
| `web/src/views/admin/Tags.vue` | 管理后台-标签管理 |
| `web/src/components/TagBadge.vue` | Tag 徽章组件 |
| `web/src/components/TagSelector.vue` | Tag 选择器组件 |
| `web/src/components/AnnouncementBanner.vue` | 公告横幅组件 |
| `web/src/components/ActivityCard.vue` | 活动卡片组件 |
| `web/src/components/RankingList.vue` | 排行榜组件 |

### 修改文件

| 文件 | 修改内容 |
|------|----------|
| `server/app/models.py` | 新增 Tag, ThreadTag, Activity, Announcement 模型；Thread 增加 pin/feature 字段 |
| `server/app/schemas.py` | 新增 Tag/Activity/Announcement 相关 schema；修改 ThreadCreate/ThreadListItem/ThreadDetail |
| `server/app/main.py` | 注册 activities 路由 |
| `server/app/routers/threads.py` | 发帖增加 tag 处理；列表增加 tag 筛选和置顶排序 |
| `server/app/routers/admin.py` | 新增 tag/活动/公告/置顶/精华/管理员发帖 API |
| `web/src/api/index.js` | 新增所有活动系统相关 API 调用 |
| `web/src/router/index.js` | 新增前后台路由 |
| `web/src/views/front/Home.vue` | 公告横幅、活动入口、置顶/精华/tag 展示 |
| `web/src/views/front/ThreadDetail.vue` | 显示 tag |
| `web/src/views/admin/Threads.vue` | 置顶/精华操作、管理员发帖 |
| `web/src/views/admin/Dashboard.vue` | 侧边栏新增入口 |
| `astrbot_plugin_astrbook/main.py` | 新增/修改工具 |
| `astrbot_plugin_astrbook/adapter/astrbook_adapter.py` | 新增事件处理 |
| `web/public/SKILL.md` | 补充 API 文档 |

---

## 🚀 执行顺序

建议严格按 Step 1 → 7 顺序执行，每步完成后可独立测试：

1. **Step 1** → 运行迁移脚本验证表创建 → ✅
2. **Step 2** → 用 curl/Postman 测试发帖带 tag → ✅
3. **Step 3** → 运行迁移 → 测试管理员活动/公告 CRUD → ✅
4. **Step 4** → 测试活动帖子查询和排行榜 → ✅
5. **Step 5** → 运行迁移 → 测试置顶/精华/管理员发帖 → ✅
6. **Step 6** → 前端联调 → ✅
7. **Step 7** → 插件测试 → ✅

---

*准备好了就告诉我开始哪一步，我们逐步实现。*
