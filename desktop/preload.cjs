const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('desktopInfo', {
  isDesktop: true,
  platform: process.platform,
})

contextBridge.exposeInMainWorld('windowControls', {
  minimize: () => ipcRenderer.send('window:minimize'),
  toggleMaximize: () => ipcRenderer.send('window:toggle-maximize'),
  close: () => ipcRenderer.send('window:close'),
  isMaximized: () => ipcRenderer.invoke('window:is-maximized'),
  onMaximizeChange: callback => {
    const handler = (_event, maximized) => callback(maximized)
    ipcRenderer.on('window:maximize-change', handler)
    return () => ipcRenderer.removeListener('window:maximize-change', handler)
  },
})
