<!-- Adapted from watt-mind/coach app/layouts/default.vue (Apache-2.0).
     Modified: local athlete only; swimming navigation; no SaaS/auth/telemetry. -->
<script setup lang="ts">
const open=ref(false)
const route=useRoute()
const links=[
 {label:'Overview',icon:'i-lucide-layout-dashboard',to:'/'},
 {label:'Swimming Analytics',icon:'i-lucide-waves',to:'/swimming'},
 {label:'Open Water',icon:'i-lucide-compass',to:'/open-water'},
 {label:'Carico e recupero',icon:'i-lucide-heart-pulse',to:'/recovery'},
 {label:'Calendario',icon:'i-lucide-calendar-days',to:'/calendar'},
 {label:'Workout Builder',icon:'i-lucide-list-plus',to:'/builder'},
 {label:'AI Coach',icon:'i-lucide-message-circle',to:'/coach'},
 {label:'Dati e sincronizzazione',icon:'i-lucide-database',to:'/data'}]
watch(()=>route.path,()=>open.value=false)
const title=computed(()=>links.find(x=>x.to===route.path)?.label || 'Dettaglio attività')
</script>
<template>
 <UDashboardGroup unit="rem">
  <UDashboardSidebar id="swim" v-model:open="open" collapsible resizable class="bg-zinc-900/40 border-r border-zinc-800" title="Navigazione" description="Garmin Coach nuoto">
   <template #header="{collapsed}"><NuxtLink to="/" class="flex gap-3 items-center py-5 px-3"><UIcon name="i-lucide-waves" class="text-green-400 size-8"/><span v-if="!collapsed" class="font-black text-lg tracking-tight">GARMIN <span class="text-green-400">COACH</span></span></NuxtLink></template>
   <template #default="{collapsed}"><p v-if="!collapsed" class="eyebrow px-3 mt-4 mb-3">Endurance · Fenix 8</p><UNavigationMenu :items="links" :collapsed="collapsed" orientation="vertical" tooltip /></template>
   <template #footer="{collapsed}"><div class="py-4 px-2"><p class="text-sm font-semibold">{{collapsed?'AD':'Atleta Demo'}}</p><p v-if="!collapsed" class="muted mt-1">Nuoto agonistico · archivio locale</p><p v-if="!collapsed" class="text-[10px] text-zinc-500 mt-4">Interfaccia derivata da Coach Watts · Apache 2.0</p></div></template>
  </UDashboardSidebar>
  <UDashboardPanel id="main">
   <template #header><UDashboardNavbar :title="title"><template #leading><UDashboardSidebarCollapse /></template><template #right><UBadge color="primary" variant="subtle" class="hidden sm:inline-flex">Dati reali Garmin</UBadge><UButton to="/coach" icon="i-lucide-message-circle" label="Coach" color="primary"/><UButton to="/data" icon="i-lucide-refresh-cw" color="neutral" variant="outline" aria-label="Sincronizzazione" /></template></UDashboardNavbar></template>
   <template #body><slot /></template>
  </UDashboardPanel>
 </UDashboardGroup>
</template>
