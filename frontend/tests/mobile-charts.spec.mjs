import {test,expect} from '@playwright/test'
import fs from 'node:fs'

for(const width of [320,390,768,1440]){
 test(`grafici leggibili e contenuti nello schermo ${width}px`,async({browser})=>{
  test.setTimeout(180000)
  const page=await browser.newPage({viewport:{width,height:900}})
  const errors=[]
  page.on('pageerror',e=>errors.push(e.message))
  fs.mkdirSync('../data/qa-mobile-charts',{recursive:true})
  let checked=0
  async function verifyCharts(){
   const charts=page.locator('.chart-area canvas')
   const count=await charts.count()
   for(let i=0;i<count;i++){
    const canvas=charts.nth(i)
    await canvas.scrollIntoViewIfNeeded()
    const info=await canvas.evaluate(element=>{
     const box=element.getBoundingClientRect(),parent=element.parentElement.getBoundingClientRect()
     const data=element.getContext('2d').getImageData(0,0,element.width,element.height).data
     let visible=0
     for(let j=0;j<data.length;j+=4){const r=data[j],g=data[j+1],b=data[j+2],a=data[j+3];if(a>100&&Math.max(r,g,b)>120&&Math.max(r,g,b)-Math.min(r,g,b)>40)visible++}
     return {left:box.left,right:box.right,width:box.width,height:box.height,parentLeft:parent.left,parentRight:parent.right,visible}
    })
    expect(info.width).toBeGreaterThan(120)
    expect(info.height).toBeGreaterThan(100)
    expect(info.left).toBeGreaterThanOrEqual(-1)
    expect(info.right).toBeLessThanOrEqual(width+1)
    expect(info.left).toBeGreaterThanOrEqual(info.parentLeft-1)
    expect(info.right).toBeLessThanOrEqual(info.parentRight+1)
    expect(info.visible).toBeGreaterThan(8)
    checked++
   }
   expect(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+2)).toBe(false)
  }
  await page.goto('http://127.0.0.1:8766/')
  await expect(page.getByRole('heading',{name:'Volume nuotato',exact:true})).toBeVisible()
  await verifyCharts()
  const activity=await page.locator('a[href^="/activity/"]').first().getAttribute('href')
  for(const path of ['/swimming','/open-water',activity]){
   expect(path).toBeTruthy()
   await page.goto('http://127.0.0.1:8766'+path)
   if(path==='/open-water'){
    const ready=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/platform/summary'&&new URL(r.url()).searchParams.get('days')==='365'&&r.ok())
    await page.getByLabel('Periodo storico',{exact:true}).selectOption('365')
    await ready
   }
   await expect(page.locator('.chart-area canvas').first()).toBeVisible()
   await verifyCharts()
  }
  await page.goto('http://127.0.0.1:8766/recovery')
  await expect(page.getByRole('heading',{name:'Copertura e valori mancanti'})).toBeVisible()
  await page.getByLabel('Fine periodo',{exact:true}).fill('2026-10-26')
  for(const tab of ['Segnali personali','Sonno','Carico','Stress e fisiologia','Associazioni']){
   await page.getByRole('button',{name:tab,exact:true}).click()
   await page.waitForTimeout(250)
   await verifyCharts()
  }
  await page.getByLabel('Giorno da approfondire',{exact:true}).fill('2026-10-25')
  await expect(page.getByRole('heading',{name:'Battito e Body Battery nel tempo'})).toBeVisible()
  await verifyCharts()
  const canvas=page.locator('.chart-area').last()
  if(await canvas.count())await canvas.screenshot({path:`../data/qa-mobile-charts/chart-${width}.png`})
  expect(checked).toBeGreaterThan(12)
  expect(errors).toEqual([])
  await page.close()
 })
}
