import {test,expect} from '@playwright/test'
import fs from 'node:fs'
const base='http://127.0.0.1:8766'
test('navigazione, dati reali, grafici e responsive', async({browser})=>{
 const output='../data/qa-dashboard'
 fs.mkdirSync(output,{recursive:true})
 for(const viewport of [{width:1440,height:1080},{width:390,height:844}]){
  const page=await browser.newPage({viewport})
  const errors=[]
  page.on('pageerror',e=>errors.push(e.message))
  for(const [path,title] of [['/','Benvenuto.'],['/swimming','Dentro ogni vasca.'],['/open-water','La distanza, senza muri.'],['/recovery','Carico, riposo e risposta.'],['/calendar','Il tuo calendario.'],['/builder','Costruisci la prossima seduta.'],['/coach','Il coach conosce il tuo storico.'],['/data','Il tuo archivio Garmin.']]){
   await page.goto(base+path)
   await expect(page.getByRole('heading',{name:title,exact:true})).toBeVisible()
   await expect(page.getByText('Dati temporaneamente non disponibili',{exact:true})).toHaveCount(0)
   if(path==='/'){
    await expect(page.locator('canvas')).toHaveCount(1)
    await expect(page.getByRole('heading',{name:'Volume nuotato',exact:true})).toBeVisible()
    await page.screenshot({path:`${output}/overview-${viewport.width}.png`,fullPage:true})
   }
   if(path==='/recovery'){
    await expect(page.locator('section.history-chart').filter({has:page.getByRole('heading',{name:'HRV notturna',exact:true})}).locator('canvas')).toHaveCount(1)
    await expect(page.locator('section.history-chart').filter({has:page.getByRole('heading',{name:'Frequenza cardiaca a riposo',exact:true})}).locator('canvas')).toHaveCount(1)
    await expect(page.getByRole('heading',{name:'Copertura e valori mancanti'})).toBeVisible()
    await page.screenshot({path:`${output}/recovery-${viewport.width}.png`,fullPage:true})
   }
   if(path==='/builder'){
    await page.getByRole('button',{name:'Calcola anteprima',exact:true}).click()
    await expect(page.getByRole('heading',{name:'Anteprima da confermare'})).toBeVisible()
    await page.screenshot({path:`${output}/builder-${viewport.width}.png`,fullPage:true})
   }
   if(path==='/coach'){
    await page.getByLabel('Provider',{exact:true}).selectOption('local')
    await page.getByRole('button',{name:'Analizza',exact:true}).click()
    await expect(page.getByText('Fatti, periodi e copertura usati nella risposta')).toBeVisible({timeout:45000})
   }
   // Horizontal scrolling is contained inside tables, never across the page.
   const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth+2)
   expect(overflow,`overflow ${viewport.width} ${path}`).toBe(false)
  }
  await page.goto(base+'/')
  await page.getByRole('link',{name:/2026-10-24/}).click()
  await expect(page.getByRole('heading',{name:'Struttura letta dai lap'})).toBeVisible()
  await expect(page.getByRole('heading',{name:'Singole vasche'})).toBeVisible()
  await page.screenshot({path:`${output}/activity-${viewport.width}.png`,fullPage:true})
  expect(errors).toEqual([])
  await page.close()
 }
})
