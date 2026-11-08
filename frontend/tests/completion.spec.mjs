import {test,expect} from '@playwright/test'
import fs from 'node:fs'

const base='http://127.0.0.1:8766'
const folder='../data/qa-completion'
const noOverflow=async(page)=>expect(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+2)).toBe(false)
const jsonAfter=async(page,path,action)=>{
 const response=page.waitForResponse(r=>new URL(r.url()).pathname===path&&r.request().method()==='POST')
 await action()
 const result=await response
 expect(result.ok(),await result.text()).toBe(true)
 return result.json()
}

for(const viewport of [{width:1440,height:1080},{width:390,height:844}]){
 test(`calendario, proposte senza salvataggio, contesto e profilo reale ${viewport.width}`,async({browser})=>{
  test.setTimeout(180000)
  fs.mkdirSync(folder,{recursive:true})
  const page=await browser.newPage({viewport})
  const errors=[],unsafe=[]
  page.on('pageerror',e=>errors.push(e.message))
  // Fail closed if a future UI change accidentally confirms a preview or calls an external model.
  await page.route('**/api/platform/**',async route=>{
   const request=route.request()
   if(request.method()==='POST'){
    const body=request.postDataJSON()||{}
    if(body.confirm||new URL(request.url()).pathname==='/api/platform/coach'&&body.provider!=='local'||new URL(request.url()).pathname==='/api/platform/intraday'){
     unsafe.push({path:new URL(request.url()).pathname,body})
     return route.abort('blockedbyclient')
    }
   }
   await route.continue()
  })
  try{
   await page.goto(base+'/calendar')
   await expect(page.getByRole('heading',{name:'Il tuo calendario.',exact:true})).toBeVisible()
   await page.getByLabel('Data calendario',{exact:true}).fill('2026-10-26')
   await expect(page.getByRole('heading',{name:'2026-10-26 → 2026-11-01',exact:true})).toBeVisible()
   await page.getByRole('button',{name:'Periodo precedente',exact:true}).click()
   await expect(page.getByRole('heading',{name:'2026-10-19 → 2026-10-25',exact:true})).toBeVisible()
   await page.getByRole('button',{name:'Periodo successivo',exact:true}).click()
   await expect(page.getByRole('heading',{name:'2026-10-26 → 2026-11-01',exact:true})).toBeVisible()
   await page.getByLabel('Vista calendario').selectOption('month')
   await expect(page.getByRole('heading',{name:/^2026-\d{2}-\d{2} → 2026-\d{2}-\d{2}$/})).toHaveCount(6)
   await expect(page.getByRole('heading',{name:'2026-11-30 → 2026-12-06',exact:true})).toBeVisible()
   await noOverflow(page)
   await page.screenshot({path:`${folder}/calendar-six-weeks-${viewport.width}.png`,fullPage:true})
   await page.getByLabel('Vista calendario').selectOption('week')
   await expect(page.getByRole('heading',{name:/^2026-\d{2}-\d{2} → 2026-\d{2}-\d{2}$/})).toHaveCount(1)
   await page.getByRole('button',{name:/HRV/}).first().click()
   await expect(page.getByRole('heading',{name:'Giornata del 2026-10-26',exact:true})).toBeVisible()
   await page.getByRole('button',{name:'Programma un blocco',exact:true}).click()
   await page.getByLabel('Obiettivo attuale',{exact:true}).fill('Anteprima QA: disponibilità da discutere con il coach')
   for(const day of ['Lun','Mar','Mer','Gio','Ven','Sab','Dom'])await page.getByLabel(day,{exact:true}).uncheck()
   await page.getByLabel('Lun',{exact:true}).check()
   await page.getByLabel('Mer',{exact:true}).check()
   await page.getByLabel('Ven',{exact:true}).check()
   await page.getByLabel('Minuti disponibili',{exact:true}).fill('60')
   // Reloading the calendar must preserve preferences that the athlete is still editing.
   await page.getByRole('button',{name:'Periodo precedente',exact:true}).click()
   await expect(page.getByRole('heading',{name:'2026-10-19 → 2026-10-25',exact:true})).toBeVisible()
   await expect(page.getByLabel('Minuti disponibili',{exact:true})).toHaveValue('60')
   for(const day of ['Lun','Mer','Ven'])await expect(page.getByLabel(day,{exact:true})).toBeChecked()
   for(const day of ['Mar','Gio','Sab','Dom'])await expect(page.getByLabel(day,{exact:true})).not.toBeChecked()
   const preferences=await jsonAfter(page,'/api/platform/memory',()=>page.getByRole('button',{name:'Anteprima preferenze',exact:true}).click())
   expect(preferences.preview.weekdays).toEqual([0,2,4])
   expect(preferences.preview.max_minutes).toBe(60)
   await expect(page.getByRole('heading',{name:'Anteprima delle preferenze',exact:true})).toBeVisible()
   await expect(page.getByRole('button',{name:'Conferma preferenze',exact:true})).toBeVisible()
   await page.getByLabel('Inizio blocco',{exact:true}).fill('2026-10-26')
   for(const weeks of [1,2,3,4]){
    await page.getByLabel('Settimane blocco',{exact:true}).selectOption(String(weeks))
    const proposal=await jsonAfter(page,'/api/platform/training',()=>page.getByRole('button',{name:'Proponi blocco dal carico recente',exact:true}).click())
    expect(proposal.preview.sessions.length).toBe(weeks*3)
    expect(proposal.preview.n_history).toBeGreaterThan(0)
    expect(proposal.preview.total_m).toBeGreaterThan(0)
    expect(proposal.preview.sessions.every(s=>[1,3,5].includes(new Date(s.date+'T12:00:00Z').getUTCDay()))).toBe(true)
    await expect(page.getByRole('heading',{name:'Anteprima del blocco',exact:true})).toBeVisible()
    await expect(page.getByRole('button',{name:'Conferma e salva il blocco',exact:true})).toBeVisible()
   }
   await noOverflow(page)
   await page.getByRole('heading',{name:'Anteprima del blocco',exact:true}).scrollIntoViewIfNeeded()
   await page.screenshot({path:`${folder}/planning-preview-${viewport.width}.png`,fullPage:true})

   await page.goto(base+'/coach')
   await page.getByText('Fatti, periodi e copertura usati nella risposta',{exact:true}).click()
   await expect(page.getByRole('columnheader',{name:'Copertura',exact:true})).toBeVisible()
   await expect(page.locator('tbody tr')).not.toHaveCount(0)
   await page.getByLabel('Provider',{exact:true}).selectOption('local')
   const answer=await jsonAfter(page,'/api/platform/coach',()=>page.getByRole('button',{name:'Analizza',exact:true}).click())
   expect(answer.context.facts.length).toBeGreaterThan(0)
   const factIds=answer.context.facts.map(f=>f.fact_id)
   for(const id of ['monitor_hrv_ms','baseline_hrv_ms','monitor_sleep_hours','week_1','week_6'])expect(factIds).toContain(id)
   expect(answer.context.training.six_weeks).toHaveLength(6)
   expect(answer.context.training.preferences.weekdays.length).toBeGreaterThan(0)
   expect(answer.answer.model).toMatch(/locale/)
   expect(answer.answer.why.length).toBeGreaterThan(0)
   expect(answer.answer.verdict).toBeTruthy()
   await expect(page.getByRole('heading',{name:'Evidenze citate dal coach',exact:true})).toBeVisible()
   await noOverflow(page)
   await page.getByRole('heading',{name:answer.answer.verdict,exact:true}).scrollIntoViewIfNeeded()
   await page.screenshot({path:`${folder}/coach-local-${viewport.width}.png`,fullPage:true})

   await page.goto(base+'/')
   await page.getByRole('link',{name:/2026-10-24/}).click()
   await expect(page.getByRole('heading',{name:'Struttura letta dai lap',exact:true})).toBeVisible()
   const editor=page.locator('details').filter({hasText:'Correggi la struttura e aggiungi il contesto della seduta'})
   await editor.locator('summary').click()
   await page.getByLabel('Intenzione seduta',{exact:true}).selectOption('tecnica')
   await page.getByLabel('Struttura dichiarata',{exact:true}).fill('Anteprima QA senza conferma: lettura dei lap registrati')
   await editor.getByRole('button',{name:'Aggiungi gruppo di lap',exact:true}).click()
   const annotation=await jsonAfter(page,'/api/platform/memory',()=>editor.getByRole('button',{name:'Anteprima struttura e contesto',exact:true}).click())
   expect(annotation.preview.intent).toBe('tecnica')
   expect(annotation.preview.sets.length).toBeGreaterThan(0)
   await expect(editor.getByRole('button',{name:'Conferma struttura e contesto',exact:true})).toBeVisible()
   await noOverflow(page)
   await editor.getByRole('heading',{name:'Anteprima da confermare',exact:true}).scrollIntoViewIfNeeded()
   await page.screenshot({path:`${folder}/manual-structure-preview-${viewport.width}.png`,fullPage:true})

   await page.goto(base+'/recovery')
   await page.getByLabel('Giorno da approfondire',{exact:true}).fill('2026-10-25')
   await expect(page.getByRole('heading',{name:'Battito e Body Battery nel tempo',exact:true})).toBeVisible()
   await expect(page.getByText('750 campioni validi su 750 registrati',{exact:false})).toBeVisible()
   await expect(page.getByText('6 campioni validi su 6 registrati',{exact:false})).toBeVisible()
   const intraday=page.locator('section').filter({has:page.getByRole('heading',{name:'Battito e Body Battery nel tempo',exact:true})})
   await expect(intraday.locator('canvas')).toHaveCount(2)
   await noOverflow(page)
   await intraday.screenshot({path:`${folder}/intraday-real-${viewport.width}.png`})
   expect(unsafe).toEqual([])
   expect(errors).toEqual([])
  }finally{await page.close()}
 })
}
