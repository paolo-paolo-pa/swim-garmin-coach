import {defineConfig} from '@playwright/test'
export default defineConfig({
 testDir:'./tests',timeout:180000,workers:1,
 outputDir:'../data/playwright-results',
 use:{headless:true,launchOptions:{executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'}},
 reporter:[['list'],['json',{outputFile:'../data/qa-dashboard/browser-results.json'}]]
})
