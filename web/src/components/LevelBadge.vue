<template>
  <span 
    class="level-badge" 
    :class="{ 'is-gradient': titleInfo.isGradient }"
    :style="badgeStyle"
    :title="`Lv.${level} - ${exp} EXP`"
  >
    <span class="level-num">Lv.{{ level }}</span>
    <span class="level-title">{{ titleInfo.title }}</span>
  </span>
</template>

<script setup>
import { computed } from 'vue'
import { getTitleForLevel } from '@/utils/levelTitle'

const props = defineProps({
  level: {
    type: Number,
    default: 1
  },
  exp: {
    type: Number,
    default: 0
  },
  size: {
    type: String,
    default: 'normal', // 'tiny', 'small', 'normal', 'large'
  }
})

const titleInfo = computed(() => getTitleForLevel(props.level))

const sizeMap = {
  tiny: '0.65rem',
  small: '0.75rem',
  normal: '0.8rem',
  large: '1rem'
}

const badgeStyle = computed(() => {
  const info = titleInfo.value
  const badgeSize = sizeMap[props.size] || sizeMap.normal
  
  if (info.isGradient) {
    return {
      background: info.color,
      color: info.textColor,
      '--badge-size': badgeSize
    }
  }
  
  return {
    backgroundColor: info.color,
    color: info.textColor,
    '--badge-size': badgeSize
  }
})
</script>

<style scoped>
.level-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: var(--badge-size, 0.8rem);
  font-weight: 500;
  white-space: nowrap;
  vertical-align: middle;
}

.level-badge.is-gradient {
  background-clip: padding-box;
  -webkit-background-clip: padding-box;
}

.level-num {
  opacity: 0.9;
}

.level-title {
  font-weight: 600;
  margin-left: 2px;
}
</style>
