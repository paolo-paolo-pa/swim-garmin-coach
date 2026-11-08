<script setup lang="ts">
import {Chart as ChartJS,LinearScale,PointElement,LineElement,Tooltip,Legend} from 'chart.js'
import {Line} from 'vue-chartjs'
ChartJS.register(LinearScale,PointElement,LineElement,Tooltip,Legend)
const props=defineProps<{points:any[],label:string,color:string,connected?:boolean}>()
const time=(v:any)=>new Date(Number(v)).toLocaleTimeString('it-IT',{hour:'2-digit',minute:'2-digit',timeZone:'Europe/Rome'})
const extent=computed(()=>{if(!props.points.length)return {};const first=new Date(props.points[0].timestamp).getTime(),last=new Date(props.points[props.points.length-1].timestamp).getTime(),pad=Math.max((last-first)*.05,60000);return {min:first-pad,max:last+pad}})
const data=computed(()=>({datasets:[{label:props.label,data:props.points.map(p=>({x:new Date(p.timestamp).getTime(),y:p.value,localTime:p.time})),borderColor:props.color,backgroundColor:props.color,borderWidth:2.5,pointRadius:props.connected?0:4,showLine:!!props.connected,tension:0,spanGaps:false}]}))
const options=computed(()=>({responsive:true,maintainAspectRatio:false,animation:false as const,parsing:false as const,plugins:{legend:{labels:{color:'#a1a1aa'}},tooltip:{callbacks:{title:(items:any[])=>items[0]?.raw?.localTime||''}}},scales:{x:{type:'linear' as const,min:extent.value.min,max:extent.value.max,ticks:{color:'#71717a',maxTicksLimit:4,maxRotation:0,minRotation:0,callback:(v:any)=>time(v)},grid:{color:'#ffffff09'}},y:{grace:'5%',ticks:{color:'#a1a1aa'},grid:{color:'#ffffff09'}}}}))
</script>
<template><div class="chart-area" v-if="points.some(p=>p.value!=null)"><Line :data="data" :options="options"/></div><p v-else class="muted py-16 text-center">Nessun dato disponibile nel periodo selezionato.</p></template>
