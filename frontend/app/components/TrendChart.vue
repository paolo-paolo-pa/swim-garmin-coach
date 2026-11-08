<script setup lang="ts">
import {Chart as ChartJS,CategoryScale,LinearScale,PointElement,LineElement,BarElement,LineController,BarController,Tooltip,Legend,Filler} from 'chart.js'
import {Bar} from 'vue-chartjs'
ChartJS.register(CategoryScale,LinearScale,PointElement,LineElement,BarElement,LineController,BarController,Tooltip,Legend,Filler)
// Una serie con `bar:true` è disegnata a barre (totali di un periodo), le altre a linea (trend, medie, riferimenti).
// `bar` sul componente rende a barre tutte le serie senza `bar:false`.
const props=defineProps<{rows:any[],x:string,series:any[],bar?:boolean,hideLegend?:boolean,temporal?:boolean}>()
const emit=defineEmits(['select'])
const isBar=(s:any)=>s.bar??props.bar??false
const has=(r:any,key:string)=>r?.[key]!=null&&Number.isFinite(Number(r[key]))
const hasData=computed(()=>props.rows.some(r=>props.series.some(s=>has(r,s.key))))
const anyBar=computed(()=>props.series.some(isBar))
// Un punto isolato (con vuoti ai due lati) non produce nessun segmento: senza un marcatore sparisce dal grafico.
function radius(s:any,key:string){
 const base=s.points===false||props.rows.length>100?0:3
 return props.rows.map((r,i)=>{
  if(!has(r,key))return 0
  const alone=!has(props.rows[i-1],key)&&!has(props.rows[i+1],key)
  return alone?4:base
 })
}
const data=computed(()=>({labels:props.rows.map(r=>r[props.x]),datasets:props.series.map((s,i)=>{
 const color=s.color||['#00dc82','#a78bfa','#60a5fa'][i%3]
 if(isBar(s))return {type:'bar' as const,label:s.label,data:props.rows.map(r=>r[s.key]),backgroundColor:color+'88',borderColor:color,borderWidth:1,borderRadius:2,maxBarThickness:28,order:2}
 return {type:'line' as const,label:s.label,data:props.rows.map(r=>r[s.key]),borderColor:color,backgroundColor:color,pointRadius:radius(s,s.key),pointHoverRadius:5,tension:0,borderWidth:Math.max(s.width||2,2),borderDash:s.dashed?[6,4]:undefined,spanGaps:false,order:1}
})}))
// Fascia chiara sui tratti in cui nessuna serie ha dati: dice «qui non c'è nulla», invece di lasciare una linea spezzata.
const gapBands={id:'gapBands',beforeDatasetsDraw(chart:any){
 const {ctx,chartArea:a,scales:{x}}=chart,n=props.rows.length,present=(i:number)=>props.series.some(s=>has(props.rows[i],s.key))
 ctx.save()
 let i=0
 while(i<n){
  if(present(i)){i++;continue}
  let j=i
  while(j<n&&!present(j))j++
  if(i>0&&j<n){
   const x0=x.getPixelForValue(i-1),x1=x.getPixelForValue(j)
   ctx.fillStyle='rgba(161,161,170,0.10)';ctx.fillRect(x0,a.top,x1-x0,a.bottom-a.top)
   if(x1-x0>70){ctx.fillStyle='#8b8b95';ctx.font='11px system-ui, sans-serif';ctx.textAlign='center';ctx.fillText('nessun dato',(x0+x1)/2,a.top+14)}
  }
  i=j
 }
 ctx.restore()
}}
const options=computed(()=>({responsive:true,maintainAspectRatio:false,animation:false as const,onClick:(_event:any,elements:any[])=>{if(elements.length)emit('select',props.rows[elements[0].index])},interaction:{intersect:false,mode:'index' as const},plugins:{legend:{display:!props.hideLegend,labels:{color:'#a1a1aa',usePointStyle:true}},tooltip:{callbacks:{title:(items:any[])=>{const row=props.rows[items[0]?.dataIndex];return row?.period_end&&row.period_end!==row[props.x]?`${row[props.x]} → ${row.period_end}`:String(row?.[props.x]??'')},afterLabel:(item:any)=>{const key=props.series[item.datasetIndex]?.key,row=props.rows[item.dataIndex];return row?.[key+'_n']!=null?`${row[key+'_n']}/${row[key+'_expected_n']} ${key.endsWith('_trend')?'osservazioni per il trend':'giorni osservati'}`:''}}}},scales:{x:{offset:true,ticks:{color:'#71717a',maxTicksLimit:6,maxRotation:0,minRotation:0,autoSkip:true,callback:(index:any)=>{const value=props.rows[index]?.[props.x];return props.temporal&&typeof value==='string'?(props.rows.length>50?value.slice(0,7):value.slice(5,10)):value}},grid:{display:false}},y:{position:'right' as const,beginAtZero:anyBar.value,ticks:{color:'#a1a1aa'},grid:{color:'#ffffff12'}}}}))
</script>
<template><div v-if="hasData" class="chart-area"><Bar :data="(data as any)" :options="(options as any)" :plugins="[gapBands]"/></div><p v-else class="muted py-16 text-center">Nessun dato disponibile nel periodo selezionato.</p></template>
