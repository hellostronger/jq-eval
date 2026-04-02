<template>
  <el-config-provider :locale="zhCn">
    <el-container class="app-container">
      <el-aside width="220px" class="app-aside">
        <div class="logo">
          <h1>JQ-Eval</h1>
          <span>RAG/LLM评估系统</span>
        </div>
        <el-menu
          :default-active="currentRoute"
          router
          class="side-menu"
        >
          <el-menu-item index="/dashboard">
            <el-icon><Odometer /></el-icon>
            <span>仪表盘</span>
          </el-menu-item>
          <el-menu-item index="/models">
            <el-icon><Setting /></el-icon>
            <span>模型配置</span>
          </el-menu-item>
          <el-menu-item index="/rag-systems">
            <el-icon><Connection /></el-icon>
            <span>RAG系统</span>
          </el-menu-item>
          <el-menu-item index="/datasets">
            <el-icon><FolderOpened /></el-icon>
            <span>数据集</span>
          </el-menu-item>
          <el-menu-item index="/evaluations">
            <el-icon><DataAnalysis /></el-icon>
            <span>评估任务</span>
          </el-menu-item>
          <el-menu-item index="/metrics">
            <el-icon><Histogram /></el-icon>
            <span>指标市场</span>
          </el-menu-item>
          <el-menu-item index="/data-sources">
            <el-icon><Database /></el-icon>
            <span>数据源</span>
          </el-menu-item>
        </el-menu>
      </el-aside>
      <el-main class="app-main">
        <router-view />
      </el-main>
    </el-container>
  </el-config-provider>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import zhCn from 'element-plus/dist/locale/zh-cn.mjs'

const route = useRoute()
const currentRoute = computed(() => route.path)
</script>

<style>
html, body, #app {
  height: 100%;
  margin: 0;
}

.app-container {
  height: 100%;
}

.app-aside {
  background: #001529;
  color: #fff;
}

.logo {
  padding: 16px;
  text-align: center;
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
}

.logo h1 {
  color: #fff;
  margin: 0;
  font-size: 20px;
}

.logo span {
  color: rgba(255, 255, 255, 0.65);
  font-size: 12px;
}

.side-menu {
  border-right: none;
  background: #001529;
}

.side-menu .el-menu-item {
  color: rgba(255, 255, 255, 0.65);
}

.side-menu .el-menu-item:hover {
  background: rgba(255, 255, 255, 0.08);
}

.side-menu .el-menu-item.is-active {
  color: #fff;
  background: #1890ff;
}

.app-main {
  background: #f0f2f5;
  padding: 16px;
}
</style>