<template>
  <div class="markdown-content" v-html="renderedContent"></div>
</template>

<script setup>
import { computed } from 'vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'

const props = defineProps({
  content: {
    type: String,
    default: ''
  }
})

// 视频文件扩展名
const VIDEO_EXTENSIONS = ['.mp4', '.webm', '.ogg', '.mov', '.m4v']

// 检查URL是否为视频
const isVideoUrl = (url) => {
  if (!url) return false
  const lowerUrl = url.toLowerCase().split('?')[0] // 移除查询参数后检查
  return VIDEO_EXTENSIONS.some(ext => lowerUrl.endsWith(ext))
}

// 解析 Bilibili 链接，返回 { bvid, page } 或 null
const parseBilibiliUrl = (url) => {
  if (!url) return null
  
  // 匹配 BV 号：BV1xx411c7mD 格式
  // 支持格式：
  // - https://www.bilibili.com/video/BV1xx411c7mD
  // - https://www.bilibili.com/video/BV1xx411c7mD?p=2
  // - https://b23.tv/BV1xx411c7mD
  // - bilibili:BV1xx411c7mD
  // - 纯 BV 号：BV1xx411c7mD
  
  const bvPattern = /(?:bilibili\.com\/video\/|b23\.tv\/|bilibili:|^)(BV[a-zA-Z0-9]+)/i
  const match = url.match(bvPattern)
  
  if (match) {
    const bvid = match[1]
    // 提取分P参数
    const pageMatch = url.match(/[?&]p=(\d+)/)
    const page = pageMatch ? parseInt(pageMatch[1]) : 1
    return { bvid, page }
  }
  
  return null
}

// 自定义 renderer，将视频链接转换为 video 标签
const renderer = new marked.Renderer()
const originalImageRenderer = renderer.image.bind(renderer)

renderer.image = function(href, title, text) {
  // 兼容 marked 不同版本的参数格式
  const url = typeof href === 'object' ? href.href : href
  const alt = typeof href === 'object' ? href.text : text
  
  // 检查是否为 Bilibili 视频
  const biliInfo = parseBilibiliUrl(url)
  if (biliInfo) {
    const { bvid, page } = biliInfo
    return `<div class="bilibili-video-wrapper">
      <iframe 
        src="https://player.bilibili.com/player.html?bvid=${bvid}&page=${page}&high_quality=1&danmaku=0&autoplay=0"
        scrolling="no"
        frameborder="0"
        allowfullscreen="true"
        class="bilibili-iframe"
        title="${alt || 'Bilibili 视频'}"
      ></iframe>
    </div>`
  }
  
  if (isVideoUrl(url)) {
    // 视频：渲染为 video 标签
    const titleAttr = title ? ` title="${title}"` : ''
    return `<video controls preload="metadata" class="markdown-video"${titleAttr}>
      <source src="${url}" type="video/${url.split('.').pop().toLowerCase()}">
      ${alt || '您的浏览器不支持视频播放'}
    </video>`
  }
  // 图片：使用原始渲染
  return originalImageRenderer(href, title, text)
}

// 配置 marked
marked.setOptions({
  breaks: true,  // 支持换行
  gfm: true,     // 支持 GitHub Flavored Markdown
  renderer: renderer
})

// 配置 DOMPurify 允许 video 和 iframe 相关标签
const sanitizeConfig = {
  ADD_TAGS: ['video', 'source', 'iframe'],
  ADD_ATTR: [
    'controls', 'preload', 'src', 'type', 'autoplay', 'loop', 'muted', 'playsinline',
    'scrolling', 'frameborder', 'allowfullscreen', 'title', 'allow'
  ]
}

// 渲染并净化 HTML
const renderedContent = computed(() => {
  if (!props.content) return ''
  const html = marked.parse(props.content)
  return DOMPurify.sanitize(html, sanitizeConfig)
})
</script>

<style lang="scss">
.markdown-content {
  line-height: 1.8;
  word-wrap: break-word;
  
  h1, h2, h3, h4, h5, h6 {
    margin: 16px 0 8px;
    font-weight: 600;
    line-height: 1.4;
  }
  
  h1 { font-size: 1.5em; }
  h2 { font-size: 1.3em; }
  h3 { font-size: 1.2em; }
  
  p {
    margin: 8px 0;
  }
  
  a {
    color: #409EFF;
    text-decoration: none;
    
    &:hover {
      text-decoration: underline;
    }
  }
  
  code {
    background: var(--md-code-bg, rgba(0, 0, 0, 0.35));
    border: 1px solid var(--md-code-border, rgba(255, 255, 255, 0.08));
    padding: 2px 6px;
    border-radius: 6px;
    font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace;
    font-size: 0.9em;
    color: var(--md-code-color, var(--acid-green));
  }
  
  pre {
    background: var(--md-pre-bg, #050507);
    border: 1px solid var(--md-pre-border, rgba(255, 255, 255, 0.08));
    padding: 14px 16px;
    border-radius: 12px;
    overflow: auto;
    margin: 14px 0;
    
    code {
      background: none;
      border: none;
      padding: 0;
      color: var(--md-pre-code-color, rgba(255, 255, 255, 0.9));
      display: block;
      line-height: 1.6;
    }
  }
  
  blockquote {
    border-left: 4px solid var(--md-blockquote-border, #dcdfe6);
    padding-left: 16px;
    margin: 12px 0;
    color: var(--md-blockquote-color, #909399);
  }
  
  ul, ol {
    padding-left: 24px;
    margin: 8px 0;
    
    li {
      margin: 4px 0;
    }
  }
  
  img {
    max-width: 100%;
    max-height: 500px; // 限制最大高度
    width: auto;
    height: auto;
    border-radius: 12px;
    margin: 16px 0;
    display: block;
    object-fit: contain; // 保持图片比例
    box-shadow: var(--md-media-shadow, 0 4px 20px rgba(0, 0, 0, 0.3));
    border: 1px solid var(--md-media-border, rgba(255, 255, 255, 0.1));
    transition: transform 0.3s ease, box-shadow 0.3s ease;
    cursor: pointer;
    
    &:hover {
      transform: scale(1.02);
      box-shadow: var(--md-media-hover-shadow, 0 8px 30px rgba(176, 38, 255, 0.3));
    }
  }
  
  // 移动端图片适配
  @media (max-width: 768px) {
    img {
      max-height: 400px;
      border-radius: 8px;
    }
  }
  
  // 视频样式
  video, .markdown-video {
    max-width: 100%;
    max-height: 500px;
    border-radius: 12px;
    margin: 16px 0;
    display: block;
    box-shadow: var(--md-media-shadow, 0 4px 20px rgba(0, 0, 0, 0.3));
    border: 1px solid var(--md-media-border, rgba(255, 255, 255, 0.1));
    background: #000;
    
    &:hover {
      box-shadow: var(--md-media-hover-shadow, 0 8px 30px rgba(176, 38, 255, 0.3));
    }
  }
  
  // 移动端视频适配
  @media (max-width: 768px) {
    video, .markdown-video {
      max-height: 300px;
      border-radius: 8px;
    }
  }
  
  // Bilibili 视频嵌入样式
  .bilibili-video-wrapper {
    position: relative;
    width: 100%;
    max-width: 800px;
    padding-bottom: 56.25%; // 16:9 比例
    margin: 16px 0;
    border-radius: 12px;
    overflow: hidden;
    background: #000;
    box-shadow: var(--md-media-shadow, 0 4px 20px rgba(0, 0, 0, 0.3));
    border: 1px solid var(--md-media-border, rgba(255, 255, 255, 0.1));
    
    &:hover {
      box-shadow: var(--md-media-hover-shadow, 0 8px 30px rgba(176, 38, 255, 0.3));
    }
    
    .bilibili-iframe {
      position: absolute;
      top: 0;
      left: 0;
      width: 100%;
      height: 100%;
      border: none;
    }
  }
  
  // 移动端 Bilibili 适配
  @media (max-width: 768px) {
    .bilibili-video-wrapper {
      border-radius: 8px;
    }
  }
  
  table {
    width: 100%;
    border-collapse: collapse;
    margin: 12px 0;
    
    th, td {
      border: 1px solid var(--md-table-border, #dcdfe6);
      padding: 8px 12px;
      text-align: left;
    }
    
    th {
      background: var(--md-table-th-bg, #f5f7fa);
      font-weight: 600;
    }
  }
  
  hr {
    border: none;
    border-top: 1px solid var(--md-hr-color, #dcdfe6);
    margin: 16px 0;
  }
}
</style>
