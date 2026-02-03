<template>
  <el-avatar 
    :size="size" 
    :src="cachedSrc" 
    :shape="shape" 
    :class="avatarClass"
    @error="handleError"
  >
    <slot></slot>
  </el-avatar>
</template>

<script setup>
import { computed, ref, watch, onMounted } from 'vue'

const props = defineProps({
  src: { type: String, default: '' },
  size: { type: [Number, String], default: 40 },
  shape: { type: String, default: 'circle' },
  avatarClass: { type: String, default: '' }
})

// 全局图片缓存 Map（内存缓存）
const imageCache = window.__avatarCache__ || (window.__avatarCache__ = new Map())

const cachedSrc = ref('')
const loadError = ref(false)

// 预加载并缓存图片
const preloadImage = (src) => {
  if (!src) return Promise.resolve('')
  
  // 检查缓存
  if (imageCache.has(src)) {
    return Promise.resolve(imageCache.get(src))
  }
  
  return new Promise((resolve) => {
    const img = new Image()
    img.onload = () => {
      imageCache.set(src, src)
      resolve(src)
    }
    img.onerror = () => {
      resolve('')
    }
    img.src = src
  })
}

const updateSrc = async () => {
  if (!props.src) {
    cachedSrc.value = ''
    return
  }
  
  // 如果已缓存，直接使用
  if (imageCache.has(props.src)) {
    cachedSrc.value = imageCache.get(props.src)
    return
  }
  
  // 否则先显示空，等加载完再更新
  const loaded = await preloadImage(props.src)
  if (loaded) {
    cachedSrc.value = loaded
  }
}

const handleError = () => {
  loadError.value = true
  cachedSrc.value = ''
}

watch(() => props.src, updateSrc, { immediate: true })

onMounted(() => {
  // 初始化时如果有缓存直接使用
  if (props.src && imageCache.has(props.src)) {
    cachedSrc.value = imageCache.get(props.src)
  }
})
</script>
