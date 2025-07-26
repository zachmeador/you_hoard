import App from './App.svelte'

console.log('File watcher test - ' + new Date())

const app = new App({
  target: document.getElementById('app')
})

export default app
