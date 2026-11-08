<script setup lang="ts">
const days=ref(28),end=ref(new Date().toLocaleDateString('sv-SE')),start=ref(''),resolution=ref('auto')
const tab=ref('signals'),selectedDay=ref(''),dailyOpen=ref(false),contextOpen=ref(false),contextLimit=ref(20)
const query=computed(()=>({days:days.value,end:end.value,start:start.value||undefined,resolution:resolution.value}))
const {data:m,error,refresh,pending}=await useFetch<any>('/api/platform/monitoring',{query})
const fmt=(v:any,n=1)=>v==null?'—':Number(v).toLocaleString('it-IT',{maximumFractionDigits:n})
const tabs=[['signals','Segnali personali'],['sleep','Sonno'],['load','Carico'],['vitals','Stress e fisiologia'],['relation','Associazioni'],['diary','Diario']]
const visibleMetrics=computed(()=>m.value?.metrics?.filter((v:any)=>['hrv_ms','resting_hr_bpm','sleep_hours','body_battery_max'].includes(v.key))||[])
const selected=computed(()=>m.value?.series?.find((r:any)=>r.date===selectedDay.value))
const selectedActivities=computed(()=>m.value?.activities?.filter((r:any)=>r.activity_date===selectedDay.value)||[])
const contextItems=computed(()=>[
 ...(m.value?.activities||[]).map((a:any)=>({id:'activity-'+a.activity_id,sourceRecordId:String(a.activity_id),kind:'wellness',sourceType:'imported',label:a.name||'Attivita Garmin',description:`${fmt(a.distance_m,0)} m · carico Garmin ${fmt(a.garmin_training_load)}`,severity:null,startAt:a.activity_date,endAt:a.activity_date,isRange:true,editable:false,deletable:false,color:'#00a155',icon:'i-lucide-waves',origin:'Garmin',category:'activity'})),
 ...(m.value?.wellness||[]).map((w:any)=>({id:w.id,sourceRecordId:w.id,kind:'daily_checkin',sourceType:'daily_checkin',label:'Feedback personale',description:w.notes||'Valutazioni confermate',severity:null,startAt:w.date,endAt:w.date,isRange:true,editable:true,deletable:false,color:'#6366f1',icon:'i-lucide-notebook-pen',origin:'Atleta',category:'wellness'}))
].sort((a:any,b:any)=>b.startAt.localeCompare(a.startAt)))
function choose(r:any){if(r.date===r.period_end){selectedDay.value=r.date;dailyOpen.value=true}}
const vitals=[
 {title:'Stress medio Garmin',unit:'/100',fields:[{key:'stress_avg',label:'Stress',color:'#fb923c'}]},
 {title:'Body Battery',unit:'/100',fields:[{key:'body_battery_min',label:'Minimo',color:'#818cf8'},{key:'body_battery_max',label:'Massimo',color:'#00dc82'}]},
 {title:'Respirazione',unit:'atti/min',fields:[{key:'respiration_avg',label:'Respirazione media',color:'#60a5fa'}]},
 {title:'SpO2',unit:'%',fields:[{key:'spo2_avg',label:'Media',color:'#c084fc'},{key:'spo2_lowest',label:'Minimo',color:'#818cf8'}]},
 {title:'Peso',unit:'kg',fields:[{key:'weight_kg',label:'Peso',color:'#fbbf24'}]},
 {title:'Passi registrati',unit:'passi',fields:[{key:'steps',label:'Passi',color:'#00dc82'}]}
]
</script>
<template>
 <div class="space-y-6 max-w-[1600px] mx-auto w-full pb-12">
  <header><p class="eyebrow">STORICO PERSONALE</p><h1 class="text-3xl font-bold mt-2">Carico, riposo e risposta.</h1><p class="muted mt-2">Leggi il trend, esplora i dati e verifica dove lo storico e incompleto.</p></header>
  <HistoryPeriod v-model:days="days" v-model:end="end" v-model:start="start" v-model:resolution="resolution"/>
  <UAlert v-if="error" color="error" title="Monitoraggio non disponibile" description="Controlla l’intervallo o riprova dopo la sincronizzazione."/>
  <p v-if="pending" role="status" class="muted">Aggiornamento del periodo…</p>
  <template v-if="m">
   <div class="grid grid-cols-2 xl:grid-cols-4 gap-4"><div v-for="v in visibleMetrics" class="panel"><p class="eyebrow">{{v.label}}</p><p class="metric mt-3">{{fmt(v.value)}} <span class="muted">{{v.unit}}</span></p><p class="muted mt-2">Ultima misura {{v.date||'non disponibile'}}<span v-if="v.status==='stale'" class="text-amber-300"> · non recente</span></p><p class="text-xs text-zinc-500 mt-3">Periodo: {{v.n}}/{{v.expected_n}} giorni con dati</p></div></div>
   <p class="muted">{{m.start}} → {{m.end}} · {{m.history.resolution_label}} · le date di inizio disponibili possono variare fra metriche.</p>
   <nav class="flex flex-wrap gap-2" aria-label="Sezioni monitoraggio"><UButton v-for="t in tabs" :key="t[0]" :color="tab===t[0]?'primary':'neutral'" :variant="tab===t[0]?'solid':'outline'" @click="tab=t[0]">{{t[1]}}</UButton></nav>
   <div v-if="tab==='signals'" class="grid lg:grid-cols-2 gap-5">
    <HistoryChart title="HRV notturna" unit="ms" :days="m.days" :history="m.history" :fields="[{key:'hrv_ms',label:'HRV',color:'#00dc82'},{key:'hrv_ms_baseline',label:'Riferimento personale 28 giorni',color:'#a1a1aa',reference:true}]" @select="choose"/>
    <HistoryChart title="Frequenza cardiaca a riposo" unit="bpm" :days="m.days" :history="m.history" :fields="[{key:'resting_hr_bpm',label:'FC riposo',color:'#fb7185'},{key:'resting_hr_bpm_baseline',label:'Riferimento personale 28 giorni',color:'#a1a1aa',reference:true}]" @select="choose"/>
   </div>
   <div v-if="tab==='sleep'" class="grid lg:grid-cols-2 gap-5">
    <div class="lg:col-span-2"><SleepStagesCard :sleep="m.sleep_breakdown"/></div>
    <HistoryChart title="Durata del sonno" unit="ore" :days="m.days" :history="m.history" :fields="[{key:'sleep_hours',label:'Sonno totale',color:'#a78bfa'},{key:'sleep_hours_baseline',label:'Riferimento personale 28 giorni',color:'#a1a1aa',reference:true}]" @select="choose"/>
    <HistoryChart title="Fasi del sonno" unit="ore" :days="m.days" :history="m.history" :fields="[{key:'deep_hours',label:'Profondo',color:'#818cf8'},{key:'rem_hours',label:'REM',color:'#c084fc'},{key:'light_hours',label:'Leggero',color:'#60a5fa'},{key:'awake_hours',label:'Sveglio',color:'#fb923c'}]" @select="choose"/>
    <HistoryChart title="Punteggio del sonno" unit="/100 Garmin" :days="m.days" :history="m.history" :fields="[{key:'sleep_score',label:'Punteggio Garmin',color:'#00dc82'}]" @select="choose"/>
   </div>
   <div v-if="tab==='load'" class="grid lg:grid-cols-2 gap-5">
    <HistoryChart title="Carico Garmin registrato" unit="carico Garmin" :days="m.days" :history="m.history" :fields="[{key:'load',label:'Carico delle attivita',color:'#00dc82'}]" bar @select="choose"/>
    <HistoryChart title="Carico acuto e cronico" unit="media giornaliera" :days="m.days" :history="m.history" :fields="[{key:'load_acute_7',label:'7 giorni',color:'#fb923c'},{key:'load_chronic_28',label:'28 giorni',color:'#60a5fa'}]" already-trend @select="choose"/>
    <details class="panel lg:col-span-2"><summary class="text-sm cursor-pointer">Metodo e disponibilita del carico</summary><p class="muted mt-3">{{m.load_method}}</p><p class="muted mt-3">{{m.readiness.note}}</p></details>
   </div>
   <div v-if="tab==='vitals'" class="grid lg:grid-cols-2 gap-5"><HistoryChart v-for="chart in vitals" :key="chart.title" :title="chart.title" :unit="chart.unit" :fields="chart.fields" :history="m.history" :days="m.days" @select="choose"/></div>
   <div v-if="tab==='relation'" class="space-y-4"><p class="muted">Associazioni esplorative fra carico e giorno successivo. Richiedono almeno 14 coppie complete e non dimostrano una causa.</p><div class="grid lg:grid-cols-2 gap-5"><div class="panel" v-for="a in m.associations"><h2 class="font-semibold mb-3">{{({hrv_ms:'HRV',resting_hr_bpm:'FC riposo',sleep_hours:'Ore di sonno'} as Record<string,string>)[a.metric]}} e carico precedente</h2><LoadAssociation :association="a" :label="a.metric"/><p class="muted mt-3">{{a.n}} coppie · Pearson r {{fmt(a.pearson_r,2)}}</p></div></div></div>
   <div v-if="tab==='diary'" class="grid lg:grid-cols-2 gap-5"><div class="panel"><WellnessForm :csrf="m.csrf" @saved="refresh"/></div><div class="panel"><h2 class="font-semibold mb-3">Feedback nel periodo</h2><div v-for="w in m.wellness" class="py-3 border-b border-zinc-800"><button class="text-green-400" @click="selectedDay=w.date;dailyOpen=true">{{w.date}}</button><p class="muted mt-2">{{w.notes}}</p></div><p v-if="!m.wellness.length" class="muted">Nessun feedback inserito.</p></div></div>
   <RecoveryCoverage :metrics="m.metrics" :note="m.coverage_note"/>
   <details class="panel"><summary class="text-sm cursor-pointer">Osservazioni e metodo personale</summary><p v-for="n in m.notices" class="muted mt-3">{{n.text}}</p><p class="muted mt-3">{{m.interpretation}}</p><p class="muted mt-3">{{m.metrics[0].note}}</p></details>
   <section class="panel space-y-4"><div class="flex flex-wrap gap-3 justify-between"><h2 class="font-semibold">Apri un giorno e le sue prove</h2><input type="date" v-model="selectedDay" aria-label="Giorno da approfondire" :min="m.start" :max="m.end" @change="dailyOpen=true"/></div><p class="muted">Nei grafici giornalieri puoi cliccare un punto; nei grafici aggregati il riquadro del punto riporta il periodo e la copertura.</p><div v-if="selected" class="space-y-2"><h3 class="text-green-400">{{selected.date}}</h3><p class="text-sm">HRV {{fmt(selected.hrv_ms)}} ms · FC riposo {{fmt(selected.resting_hr_bpm)}} bpm · sonno {{fmt(selected.sleep_hours)}} h · carico {{fmt(selected.load)}}</p><NuxtLink v-for="a in selectedActivities" :to="'/activity/'+a.activity_id" class="block text-green-400 text-sm">{{a.name}} · {{fmt(a.distance_m,0)}} m → dettaglio</NuxtLink><p v-if="!selectedActivities.length" class="muted">Nessuna attivita registrata. Non certifica riposo.</p></div><UButton variant="outline" @click="dailyOpen=!dailyOpen">{{dailyOpen?'Nascondi profilo orario':'Mostra profilo orario del giorno'}}</UButton></section>
   <IntradayPanel v-if="dailyOpen" :csrf="m.csrf" :date="selectedDay||end"/>
   <details class="panel" @toggle="contextOpen=($event.target as HTMLDetailsElement).open"><summary class="font-semibold cursor-pointer">Sedute e diario del periodo</summary><template v-if="contextOpen"><RecoveryContextTimeline :items="contextItems.slice(0,contextLimit)" :show-view-all="false" @select="selectedDay=$event.startAt.slice(0,10);dailyOpen=true"/><UButton v-if="contextItems.length>contextLimit" class="mt-3" variant="outline" @click="contextLimit+=20">Mostra altre 20 voci</UButton></template></details>
  </template>
 </div>
</template>
