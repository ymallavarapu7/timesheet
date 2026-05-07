export async function registerTimerSW() {
  if (!('serviceWorker' in navigator)) {
    console.warn('Service workers are not supported by this browser.');
    return;
  }

  try {
    const registration = await navigator.serviceWorker.register('/timer-sw.js', {
      scope: '/'
    });
    console.log('Timer Service Worker registered with scope:', registration.scope);
  } catch (error) {
    console.error('Timer Service Worker registration failed:', error);
  }
}

export function pingServiceWorker(): Promise<{ elapsedMs: number, status: string }> {
  return new Promise((resolve, reject) => {
    if (!navigator.serviceWorker || !navigator.serviceWorker.controller) {
      reject(new Error('No active Service Worker controller'));
      return;
    }

    const messageChannel = new MessageChannel();

    messageChannel.port1.onmessage = (event) => {
      if (event.data && event.data.type === 'TIMER_PONG') {
        resolve({
          elapsedMs: event.data.elapsedMs,
          status: event.data.status
        });
      }
    };

    setTimeout(() => {
      reject(new Error('Service Worker ping timeout'));
    }, 1000);

    navigator.serviceWorker.controller.postMessage(
      { type: 'TIMER_PING' },
      [messageChannel.port2]
    );
  });
}

export function notifyServiceWorker(type: 'TIMER_START' | 'TIMER_PAUSE' | 'TIMER_RESUME' | 'TIMER_STOP', payload?: any) {
  if (navigator.serviceWorker && navigator.serviceWorker.controller) {
    navigator.serviceWorker.controller.postMessage({
      type,
      ...payload
    });
  }
}
