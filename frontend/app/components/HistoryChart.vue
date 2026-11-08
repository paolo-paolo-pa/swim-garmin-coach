<script setup lang="ts">
const props=defineProps<{history:any,fields:any[],unit:string,title:string,days:number,bar?:boolean,alreadyTrend?:boolean}>()
const emit=defineEmits(['select'])
const mode=ref(props.alreadyTrend?'trend':props.bar?'both':props.days>90?'trend':'both')
const selected=ref<string[]>(props.fields.filter(f=>!f.reference).map(f=>f.key))
const picked=ref<any>(null)
const trim=ref(props.days>90)
const visibleRows=computed(()=>{
 if(!trim.value)return props.history.rows
 const present=(r:any)=>props.fields.some(f=>selected.value.includes(f.key)&&r[f.key]!=null)
 const first=props.history.rows.findIndex(present)
 let last=props.history.rows.length-1
 while(last>=first&&!present(props.history.rows[last]))last--
 return first<0?[]:props.history.rows.slice(first,last+1)
})
watch(()=>props.days,v=>{mode.value=props.alreadyTrend?'trend':props.bar?'both':v>90?'trend':'both';picked.value=null;trim.value=v>90})
const series=computed(()=>props.fields.filter(f=>selected.value.includes(f.key)).flatMap((f,i)=>{
 const color=f.color||['#00dc82','#a78bfa','#60a5fa','#fb923c'][i%4]
 if(f.reference)return [{key:f.key,label:f.label,color,dashed:true,points:false}]
 if(props.alreadyTrend)return [{key:f.key,label:f.label,color,points:false,bar:false}]
 const raw={key:f.key,label:f.label+(props.history.resolution==='day'?' · dati':' · '+(props.history.aggregation[f.key]==='sum'?'totale periodo':'media periodo')),color,points:mode.value==='raw',bar:!!props.bar}
 const trend={key:f.key+'_trend',label:f.label+' · trend',color,points:false,width:2.5,bar:false}
 return mode.value==='trend'?[trend]:mode.value==='raw'?[raw]:props.bar?[raw,trend]:[{...raw,dashed:true,width:2},trend]
}))
const method=computed(()=>props.fields.filter(f=>!f.reference&&selected.value.includes(f.key)).map(f=>props.history.trend_methods[f.key]).filter((v,i,a)=>a.indexOf(v)===i))
const trendMissing=computed(()=>mode.value==='trend'&&!props.alreadyTrend&&!visibleRows.value.some((r:any)=>series.value.some(s=>r[s.key]!=null)))
const fmt=(v:any)=>v==null?'—':Number(v).toLocaleString('it-IT',{maximumFractionDigits:2})
function choose(row:any){picked.value=row;emit('select',row)}
</script>
<template><section class="panel space-y-4 history-chart" :aria-label="title"><div class="flex flex-wrap justify-between gap-3 items-start"><div><h2 class="font-semibold">{{title}}</h2><p class="muted mt-1">{{unit}} · {{history.resolution_label.toLowerCase()}}</p></div><div v-if="!alreadyTrend" class="flex gap-1 rounded-lg bg-zinc-900 p-1" role="group" :aria-label="'Vista '+title"><button v-for="choice in [['trend','Solo trend'],['raw','Dati'],['both','Entrambi']]" :aria-pressed="mode===choice[0]" class="px-3 py-1.5 rounded-md text-xs" :class="mode===choice[0]?'bg-green-600 text-white':'text-zinc-400'" @click="mode=choice[0]">{{choice[1]}}</button></div></div><div class="flex flex-wrap gap-3"><label v-for="f in fields" class="text-xs flex items-center gap-2"><input type="checkbox" v-model="selected" :value="f.key" :aria-label="f.label+' · '+title"/><span class="w-2 h-2 rounded-full" :style="{backgroundColor:f.color||'#00dc82'}"/>{{f.label}}<span v-if="f.reference" class="text-zinc-500">riferimento</span></label></div><label class="text-xs text-zinc-500 flex gap-2 items-center"><input type="checkbox" v-model="trim"/>Limita il grafico al periodo con misure</label><p v-if="trim&&visibleRows.length" class="text-xs text-zinc-500">Misure visibili: {{visibleRows[0].date}} → {{visibleRows[visibleRows.length-1].period_end}}. I periodi interamente privi di misure restano interruzioni.</p><p v-if="!selected.length" class="muted py-10 text-center">Seleziona almeno una serie.</p><TrendChart v-else :rows="visibleRows" x="date" :series="series" :bar="false" :hide-legend="true" temporal @select="choose"/><p v-if="mode==='both'&&!alreadyTrend" class="text-xs text-zinc-500">{{bar?'Barre: totale del periodo (una barra bassa o assente = nessuna nuotata registrata). Linea: trend.':'Linea tratteggiata: dati del periodo. Linea continua: trend.'}} Il colore identifica la serie selezionata.</p><p v-if="trendMissing" class="text-sm text-amber-300">Campioni insufficienti per il trend. Seleziona «Dati» per vedere le misure disponibili.</p><p v-if="mode==='trend'&&!alreadyTrend" class="text-xs text-zinc-500">Il trend attenua le oscillazioni; non sostituisce i giorni mancanti. I dati restano consultabili con «Dati» o «Entrambi».</p><div v-if="picked" class="rounded-lg border border-zinc-800 p-3 text-xs space-y-2"><p class="font-semibold">{{picked.date}}<span v-if="picked.period_end!==picked.date"> → {{picked.period_end}}</span></p><p v-for="f in fields.filter(f=>selected.includes(f.key))">{{f.label}}: {{fmt(picked[f.key])}} {{unit}} · {{picked[f.key+'_n']??'—'}}/{{picked[f.key+'_expected_n']??'—'}} giorni osservati<span v-if="!f.reference&&!alreadyTrend"> · trend {{fmt(picked[f.key+'_trend'])}} {{unit}}</span></p></div><details class="text-xs text-zinc-500"><summary class="cursor-pointer">Come leggere questo grafico</summary><p class="mt-2">{{history.resolution==='day'?'Ogni punto rappresenta un giorno.':'Ogni punto riassume un periodo; il tooltip riporta giorni osservati e giorni attesi.'}} {{bar?'Nel volume, un periodo senza nuotate è 0 km quando l’orologio era in uso (ci sono altri dati Garmin); la fascia grigia «nessun dato» indica invece un periodo senza alcun dato.':'Le interruzioni, evidenziate da una fascia grigia, corrispondono a periodi senza valori, non a zero.'}}</p><p v-if="alreadyTrend" class="mt-2">Queste linee sono già medie mobili calcolate dal backend. Puoi attivarle singolarmente.</p><p v-else v-for="text in method" class="mt-2">{{text}}.</p><p class="mt-2" v-if="fields.some(f=>f.reference)">Il riferimento personale è distinto dal trend: usa le misure precedenti al singolo giorno.</p></details></section></template>
