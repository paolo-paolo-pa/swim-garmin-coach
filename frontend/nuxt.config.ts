// Local adaptation of Coach Watts: Nuxt UI frontend; canonical Python backend.
export default defineNuxtConfig({
  ssr: false,
  modules: ['@nuxt/ui'],
  ui: {fonts: false},
  css: ['~/assets/css/main.css'],
  devtools: {enabled: false},
  app: {head: {title: 'Garmin Coach · Nuoto endurance', htmlAttrs: {lang:'it', class:'dark'}}},
  fonts: {providers: {google: false, bunny: false}},
  icon: {clientBundle: {scan: true}, provider: 'none'},
  colorMode: {preference: 'dark', fallback: 'dark'},
  nitro: {devProxy: {'/api/platform': {target: 'http://127.0.0.1:8766/api/platform', changeOrigin: false}}}
})
