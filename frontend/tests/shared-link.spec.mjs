import {test,expect} from '@playwright/test'

test('link condiviso: dashboard visibile e scrittura bloccata',async({browser})=>{
 const base=process.env.GARMIN_SHARE_URL
 test.skip(!base,'Impostare GARMIN_SHARE_URL al link temporaneo da verificare')
 const page=await browser.newPage({viewport:{width:390,height:844}})
 const errors=[]
 page.on('pageerror',e=>errors.push(e.message))
 await page.goto(base+'/recovery',{waitUntil:'domcontentloaded'})
 await expect(page.getByRole('heading',{name:'Copertura e valori mancanti'})).toBeVisible({timeout:45000})
 await expect(page.locator('.chart-area canvas').first()).toBeVisible()
 expect((await page.request.post(base+'/api/platform/sync')).status()).toBe(405)
 expect(errors).toEqual([])
 await page.close()
})
