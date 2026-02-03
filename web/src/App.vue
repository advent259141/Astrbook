<template>
  <div class="app-shell">
    <div class="route-progress" :class="{ active: isRouteLoading }"></div>

    <router-view v-slot="{ Component, route }">
      <transition name="route" mode="out-in">
        <!-- key by top-level route record to avoid remounting layouts on every navigation -->
        <component :is="Component" :key="route.matched?.[0]?.path || route.path" />
      </transition>
    </router-view>
  </div>
</template>

<script setup>
import { isRouteLoading } from './state/routeLoading'
</script>

<style lang="scss">
.app-shell {
  position: relative;
  min-height: 100vh;
  min-height: 100dvh;
}

.route-progress {
  position: fixed;
  top: var(--safe-top);
  left: 0;
  width: 100%;
  height: 2px;
  z-index: 9999;
  pointer-events: none;

  &::before {
    content: '';
    position: absolute;
    left: -45%;
    width: 45%;
    height: 100%;
    opacity: 0;
    background: linear-gradient(90deg, transparent, var(--acid-green), var(--acid-blue), transparent);
    filter: drop-shadow(0 0 8px rgba(204, 255, 0, 0.35));
    transform: translateX(0);
  }

  &.active::before {
    opacity: 1;
    animation: route-progress-sweep 0.9s var(--ease-out) infinite;
  }
}

@keyframes route-progress-sweep {
  0% {
    transform: translateX(0);
  }
  100% {
    transform: translateX(320%);
  }
}
</style>
