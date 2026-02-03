<template>
  <div class="admin-layout">
    <Sidebar />
    <div class="main-content">
      <Header />
      <div class="page-content">
        <router-view v-slot="{ Component, route }">
          <transition name="route" mode="out-in">
            <keep-alive :include="keepAliveInclude">
              <component :is="Component" :key="route.fullPath" />
            </keep-alive>
          </transition>
        </router-view>
      </div>
    </div>
  </div>
</template>

<script setup>
import Sidebar from '../components/admin/Sidebar.vue'
import Header from '../components/admin/Header.vue'

const keepAliveInclude = ['AdminDashboard', 'AdminThreads', 'AdminUsers']
</script>

<style lang="scss" scoped>
.admin-layout {
  display: flex;
  min-height: 100vh;
  background: transparent;
}

.main-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.page-content {
  flex: 1;
  padding: 24px;
  overflow-y: auto;
  max-width: 1600px;
  margin: 0 auto;
  width: 100%;
}
</style>
