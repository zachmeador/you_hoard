<script>
  import { onMount } from 'svelte'
  import { fade } from 'svelte/transition'
  
  let toasts = []
  let nextId = 0

  function addToast(message, type = 'info', duration = 5000) {
    const id = nextId++
    const toast = { id, message, type }
    
    toasts = [...toasts, toast]
    
    setTimeout(() => {
      removeToast(id)
    }, duration)
  }

  function removeToast(id) {
    toasts = toasts.filter(toast => toast.id !== id)
  }

  onMount(() => {
    const handleShowToast = (event) => {
      const { message, type, duration } = event.detail
      addToast(message, type, duration)
    }

    document.addEventListener('show-toast', handleShowToast)
    
    return () => {
      document.removeEventListener('show-toast', handleShowToast)
    }
  })
</script>

<div class="toast-container">
  {#each toasts as toast (toast.id)}
    <div class="toast {toast.type}" in:fade={{duration: 300}} out:fade={{duration: 300}}>
      <div>{toast.message}</div>
    </div>
  {/each}
</div> 