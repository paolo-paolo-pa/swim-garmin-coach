<script setup lang="ts">
import{Chart as ChartJS,LinearScale,PointElement,Tooltip,Legend}from'chart.js'
import{Scatter}from'vue-chartjs'
ChartJS.register(LinearScale,PointElement,Tooltip,Legend)
const props=defineProps<{association:any,label:string}>()
const data=computed(()=>({datasets:[{label:props.label,data:props.association.pairs.map((p:any)=>({x:p.load,y:p.value,date:p.date,load_date:p.load_date})),backgroundColor:'#00dc82',pointRadius:4}]}))
const options={responsive:true,maintainAspectRatio:false,plugins:{legend:{labels:{color:'#a1a1aa'}},tooltip:{callbacks:{afterLabel:(c:any)=>`${c.raw.load_date} → ${c.raw.date}`}}},scales:{x:{title:{display:true,text:'Carico Garmin del giorno precedente',color:'#a1a1aa'},ticks:{color:'#a1a1aa',maxTicksLimit:5,maxRotation:0},grid:{color:'#ffffff09'}},y:{ticks:{color:'#a1a1aa'},grid:{color:'#ffffff09'}}}}
</script>
<template><div class="chart-area" v-if="association.pairs.length"><Scatter :data="data" :options="options"/></div><p v-else class="muted py-8">Nessuna coppia completa disponibile.</p></template>
