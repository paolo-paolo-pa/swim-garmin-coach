import {test,expect} from '@playwright/test'
import fs from 'node:fs'

const base='http://127.0.0.1:8766'
const chart=(page,title)=>page.locator('section.history-chart').filter({has:page.getByRole('heading',{name:title,exact:true})})
const change=async(page,label,value,path='/api/platform/monitoring')=>{
 const response=page.waitForResponse(r=>new URL(r.url()).pathname===path&&r.ok()&&(label!=='Periodo storico'||new URL(r.url()).searchParams.get('days')===value)&&(label!=='Dettaglio grafici'||new URL(r.url()).searchParams.get('resolution')===value))
 await page.getByLabel(label,{exact:true}).selectOption(value)
 return (await response).json()
}

for(const viewport of [{width:1440,height:1080},{width:390,height:844}]){
 test(`storico lungo, buchi e serie selezionabili ${viewport.width}`,async({browser})=>{
  const page=await browser.newPage({viewport})
  const errors=[]
  page.on('pageerror',e=>errors.push(e.message))
  fs.mkdirSync('../data/qa-history',{recursive:true})
  await page.goto(base+'/recovery')
  await expect(page.getByRole('heading',{name:'Copertura e valori mancanti',exact:true})).toBeVisible()
  await page.getByLabel('Fine periodo',{exact:true}).fill('2026-10-26')
  for(const [days,resolution,count] of [['365','week',53],['730','week',106],['1825','month',61],['0','month',110]]){
   const data=await change(page,'Periodo storico',days)
   expect(data.history.resolution).toBe(resolution)
   expect(data.history.rows.length).toBe(count)
   await expect(chart(page,'HRV notturna').getByRole('button',{name:'Solo trend',exact:true})).toHaveAttribute('aria-pressed','true')
  }
  const hrv=chart(page,'HRV notturna')
  await expect(hrv.locator('canvas')).toHaveCount(1)
  await hrv.getByRole('button',{name:'Dati',exact:true}).click()
  await expect(hrv.getByRole('button',{name:'Dati',exact:true})).toHaveAttribute('aria-pressed','true')
  await hrv.getByLabel('HRV · HRV notturna',{exact:true}).uncheck()
  await expect(hrv.getByText('Seleziona almeno una serie.',{exact:true})).toBeVisible()
  await hrv.getByLabel('HRV · HRV notturna',{exact:true}).check()
  await hrv.getByRole('button',{name:'Entrambi',exact:true}).click()
  await page.getByText('Dove sono i buchi e che cosa sappiamo',{exact:true}).click()
  await expect(page.getByText('Prima della prima misura disponibile',{exact:false}).first()).toBeVisible()
  await hrv.scrollIntoViewIfNeeded()
  await hrv.screenshot({path:`../data/qa-history/alltime-signals-${viewport.width}.png`})
  await page.getByRole('button',{name:'Sonno',exact:true}).click()
  await expect(page.getByRole('heading',{name:'L’ultima notte registrata',exact:true})).toBeVisible()
  const stages=chart(page,'Fasi del sonno')
  await stages.getByLabel('REM · Fasi del sonno',{exact:true}).uncheck()
  await expect(stages.locator('canvas')).toHaveCount(1)
  await stages.getByRole('button',{name:'Dati',exact:true}).click()
  const monthly=await change(page,'Dettaglio grafici','month')
  expect(monthly.history.resolution).toBe('month')
  await stages.screenshot({path:`../data/qa-history/alltime-sleep-${viewport.width}.png`})
  await page.getByLabel('Intervallo personalizzato',{exact:true}).check()
  const customResponse=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/platform/monitoring'&&r.ok())
  await page.getByLabel('Inizio periodo',{exact:true}).fill('2026-10-01')
  const custom=await (await customResponse).json()
  expect(custom.days).toBe(26)
  expect(custom.metrics.find(m=>m.key==='sleep_score').n).toBe(26)
  expect(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+2)).toBe(false)
  await page.goto(base+'/')
  const overview=await change(page,'Periodo storico','0','/api/platform/summary')
  expect(overview.start<'2017-01-01').toBe(true)
  expect(overview.volume_history.resolution).toBe('month')
  await expect(chart(page,'Volume nuotato').locator('canvas')).toHaveCount(1)
  await chart(page,'Volume nuotato').screenshot({path:`../data/qa-history/alltime-volume-${viewport.width}.png`})
  expect(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+2)).toBe(false)
  expect(errors).toEqual([])
  await page.close()
 })
}
