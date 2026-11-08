import {test,expect} from '@playwright/test'
import fs from 'node:fs'

test('monitoraggio approfondito e confronti nuoto su desktop e telefono',async({browser})=>{
 test.setTimeout(150000)
 const folder='../data/qa-monitoring'
 fs.mkdirSync(folder,{recursive:true})
 for(const viewport of [{width:1440,height:1080},{width:390,height:844}]){
  const page=await browser.newPage({viewport})
  const errors=[]
  page.on('pageerror',e=>errors.push(e.message))
  await page.goto('http://127.0.0.1:8766/recovery')
  await expect(page.getByRole('heading',{name:'Copertura e valori mancanti'})).toBeVisible()
  await expect(page.locator('section.history-chart').filter({has:page.getByRole('heading',{name:'HRV notturna',exact:true})}).locator('canvas')).toHaveCount(1)
  await expect(page.locator('section.history-chart').filter({has:page.getByRole('heading',{name:'Frequenza cardiaca a riposo',exact:true})}).locator('canvas')).toHaveCount(1)
  await page.screenshot({path:`${folder}/signals-${viewport.width}.png`,fullPage:true})
  await page.getByRole('button',{name:'Sonno',exact:true}).click()
  await expect(page.getByRole('heading',{name:'L’ultima notte registrata'})).toBeVisible()
  for(const title of ['Durata del sonno','Fasi del sonno','Punteggio del sonno'])
   await expect(page.locator('section.history-chart').filter({has:page.getByRole('heading',{name:title,exact:true})}).locator('canvas')).toHaveCount(1)
  await page.screenshot({path:`${folder}/sleep-${viewport.width}.png`,fullPage:true})
  await page.getByRole('button',{name:'Stress e fisiologia',exact:true}).click()
  await expect(page.getByRole('heading',{name:'Peso',exact:true})).toBeVisible()
  await expect(page.locator('section.history-chart').filter({has:page.getByRole('heading',{name:'Peso',exact:true})}).getByText('Nessun dato disponibile nel periodo selezionato.',{exact:true})).toBeVisible()
  await page.getByRole('button',{name:'Associazioni',exact:true}).click()
  for(const title of ['HRV e carico precedente','FC riposo e carico precedente','Ore di sonno e carico precedente'])
   await expect(page.getByRole('heading',{name:title,exact:true}).locator('..').locator('canvas')).toHaveCount(1)
  await page.getByRole('button',{name:'Diario',exact:true}).click()
  await page.getByLabel('Fatica',{exact:true}).selectOption('5')
  await page.getByRole('button',{name:'Anteprima feedback',exact:true}).click()
  await expect(page.getByRole('button',{name:'Conferma feedback',exact:true})).toBeVisible()
  // No fabricated sensations are confirmed in the real athlete's memory.
  await page.getByLabel('Giorno da approfondire').fill('2026-10-24')
  await expect(page.getByRole('link',{name:/dettaglio/})).toBeVisible()
  expect(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+2)).toBe(false)
  await page.goto('http://127.0.0.1:8766/swimming')
  await expect(page.getByRole('heading',{name:'Le ripetute, seduta per seduta.'})).toBeVisible()
  await expect(page.getByRole('heading',{name:'Sedute che sostengono il confronto'})).toBeVisible()
  await page.getByRole('button',{name:/2026-10-24/}).click()
  await expect(page.getByRole('heading',{name:'Ripetute del 2026-10-24'})).toBeVisible()
  await page.getByLabel('Distanza ripetuta').selectOption('400')
  await expect(page.getByRole('heading',{name:'Ripetute del 2026-10-24'})).toHaveCount(0)
  await page.screenshot({path:`${folder}/swim-comparison-${viewport.width}.png`,fullPage:true})
  expect(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+2)).toBe(false)
  expect(errors).toEqual([])
  await page.close()
 }
})
