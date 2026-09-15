<script setup lang="ts">
import { RouterView } from 'vue-router'
import AppHeader from '@/components/AppHeader.vue'
import AppFooter from '@/components/AppFooter.vue'
import ChatWidget from '@/components/ChatWidget.vue'
</script>

<template>
  <AppHeader />
  <main class="min-h-[calc(100vh-200px)]">
    <RouterView />
  </main>
  <AppFooter />
  <ChatWidget />
</template>
