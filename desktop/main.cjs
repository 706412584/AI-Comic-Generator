// AI Comic Generator 桌面壳：负责启动/守护 FastAPI sidecar，健康检查通过后再打开主窗口。
// 参考 cc-haha 的 serverRuntime/sidecarManager 模式（简化版）。
const { app, BrowserWindow, dialog, shell, ipcMain } = require('electron')
const { spawn, execFile } = require('node:child_process')
const net = require('node:net')
const path = require('node:path')
const fs = require('node:fs')
const crypto = require('node:crypto')

const IS_DEV = process.argv.includes('--dev')
const PREFERRED_PORTS = [48730, 48731, 48732, 48733, 48734]
const EXPECTED_BACKEND_APP = 'AI Comic Generator'
const HEALTH_TIMEOUT_MS = 60_000
const HEALTH_POLL_INTERVAL_MS = 500
const BACKEND_AUTH_TOKEN = crypto.randomBytes(32).toString('hex')

let mainWindow = null
let loadingWindow = null
let backendProcess = null
let backendPort = null
let isQuitting = false

// ---------- 日志 ----------

function logFile() {
  const dir = path.join(app.getPath('userData'), 'logs')
  fs.mkdirSync(dir, { recursive: true })
  return path.join(dir, 'desktop.log')
}

function log(message) {
  const line = `[${new Date().toISOString()}] ${message}\n`
  try {
    fs.appendFileSync(logFile(), line)
  } catch {
    // 日志失败不影响主流程
  }
  if (IS_DEV) process.stdout.write(line)
}

// ---------- 端口 ----------

function checkPortFree(port) {
  return new Promise(resolve => {
    const server = net.createServer()
    server.once('error', () => resolve(false))
    server.once('listening', () => {
      server.close(() => resolve(true))
    })
    server.listen(port, '127.0.0.1')
  })
}

async function pickPort() {
  for (const port of PREFERRED_PORTS) {
    if (await checkPortFree(port)) return port
  }
  // 全被占用则让系统分配
  return new Promise((resolve, reject) => {
    const server = net.createServer()
    server.once('error', reject)
    server.listen(0, '127.0.0.1', () => {
      const port = server.address().port
      server.close(() => resolve(port))
    })
  })
}

// ---------- 后端 sidecar ----------

function backendDataDir() {
  const dir = path.join(app.getPath('userData'), 'data')
  fs.mkdirSync(dir, { recursive: true })
  return dir
}

function resolveBackendCommand(port) {
  const env = {
    ...process.env,
    COMIC_APP_DATA_DIR: backendDataDir(),
    COMIC_APP_PORT: String(port),
    COMIC_APP_AUTH_TOKEN: BACKEND_AUTH_TOKEN,
  }

  if (app.isPackaged) {
    const exe = path.join(process.resourcesPath, 'backend', 'AI-Comic-Generator.exe')
    return { command: exe, args: ['--port', String(port)], cwd: path.dirname(exe), env }
  }

  const backendDir = path.resolve(__dirname, '..', 'backend')
  return {
    command: 'python',
    args: ['run_server.py', '--port', String(port)],
    cwd: backendDir,
    env,
  }
}

function spawnBackend(port) {
  const plan = resolveBackendCommand(port)
  log(`Starting backend: ${plan.command} ${plan.args.join(' ')} (cwd=${plan.cwd})`)

  const child = spawn(plan.command, plan.args, {
    cwd: plan.cwd,
    env: plan.env,
    stdio: ['ignore', 'pipe', 'pipe'],
    windowsHide: true,
  })

  child.stdout.on('data', chunk => log(`[backend] ${String(chunk).trimEnd()}`))
  child.stderr.on('data', chunk => log(`[backend:err] ${String(chunk).trimEnd()}`))
  child.on('exit', (code, signal) => {
    log(`Backend exited: code=${code} signal=${signal}`)
    backendProcess = null
    if (!isQuitting) {
      dialog.showErrorBox(
        'AI Comic Generator',
        `后端服务意外退出（code=${code}）。\n日志文件：${logFile()}`,
      )
      app.quit()
    }
  })

  return child
}

async function waitForHealth(port) {
  const url = `http://127.0.0.1:${port}/api/v1/health`
  const deadline = Date.now() + HEALTH_TIMEOUT_MS
  while (Date.now() < deadline) {
    if (isQuitting) throw new Error('quitting')
    if (!backendProcess) throw new Error('后端进程已退出')
    try {
      const res = await fetch(url, {
        headers: { 'X-Comic-App-Token': BACKEND_AUTH_TOKEN },
        signal: AbortSignal.timeout(2000),
      })
      if (res.ok) {
        const health = await res.json()
        if (health.status === 'ok' && health.app === EXPECTED_BACKEND_APP) return
      }
    } catch {
      // 未就绪或端口上的服务不是本应用，继续等待
    }
    await new Promise(resolve => setTimeout(resolve, HEALTH_POLL_INTERVAL_MS))
  }
  throw new Error(`后端在 ${HEALTH_TIMEOUT_MS / 1000}s 内未就绪`)
}

function killBackend() {
  if (!backendProcess) return
  const pid = backendProcess.pid
  log(`Killing backend pid=${pid}`)
  try {
    if (process.platform === 'win32') {
      // Windows 上需要杀掉整棵进程树（uvicorn 可能有子进程）
      execFile('taskkill', ['/pid', String(pid), '/T', '/F'])
    } else {
      backendProcess.kill('SIGTERM')
    }
  } catch (error) {
    log(`Failed to kill backend: ${error}`)
  }
  backendProcess = null
}

// ---------- 窗口 ----------

function createLoadingWindow() {
  loadingWindow = new BrowserWindow({
    width: 420,
    height: 260,
    frame: false,
    resizable: false,
    show: true,
    backgroundColor: '#111111',
    webPreferences: { contextIsolation: true },
  })
  loadingWindow.loadFile(path.join(__dirname, 'loading.html'))
  loadingWindow.on('closed', () => {
    loadingWindow = null
  })
}

function createMainWindow(port) {
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 1024,
    minHeight: 700,
    show: false,
    frame: false,
    autoHideMenuBar: true,
    title: 'AI Comic Generator',
    backgroundColor: '#111111',
    icon: path.join(__dirname, 'icon.ico'),
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      preload: path.join(__dirname, 'preload.cjs'),
    },
  })

  mainWindow.webContents.session.webRequest.onBeforeSendHeaders(
    { urls: [`http://127.0.0.1:${port}/*`] },
    (details, callback) => {
      details.requestHeaders['X-Comic-App-Token'] = BACKEND_AUTH_TOKEN
      callback({ requestHeaders: details.requestHeaders })
    },
  )

  const isAppUrl = url => {
    try {
      const parsed = new URL(url)
      return (
        (parsed.protocol === 'http:' || parsed.protocol === 'https:') &&
        parsed.hostname === '127.0.0.1' &&
        String(parsed.port || (parsed.protocol === 'https:' ? '443' : '80')) === String(port)
      )
    } catch {
      return false
    }
  }
  const isSafeExternalHttp = url => {
    try {
      const parsed = new URL(url)
      return parsed.protocol === 'https:' || parsed.protocol === 'http:'
    } catch {
      return false
    }
  }

  // 仅允许本应用 origin；外部 http(s) 走系统浏览器；拒绝 javascript:/data: 等
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (isAppUrl(url)) return { action: 'allow' }
    if (isSafeExternalHttp(url) && !isAppUrl(url)) {
      shell.openExternal(url)
    }
    return { action: 'deny' }
  })

  mainWindow.webContents.on('will-navigate', (event, url) => {
    if (isAppUrl(url)) return
    event.preventDefault()
    if (isSafeExternalHttp(url)) shell.openExternal(url)
  })

  mainWindow.once('ready-to-show', () => {
    if (loadingWindow) {
      loadingWindow.close()
      loadingWindow = null
    }
    mainWindow.show()
  })

  const emitMaximizeState = () => {
    if (!mainWindow || mainWindow.isDestroyed()) return
    mainWindow.webContents.send('window:maximize-change', mainWindow.isMaximized())
  }
  mainWindow.on('maximize', emitMaximizeState)
  mainWindow.on('unmaximize', emitMaximizeState)

  mainWindow.on('closed', () => {
    mainWindow = null
  })

  mainWindow.loadURL(`http://127.0.0.1:${port}/`)
}

// ---------- 窗口控制 IPC ----------

ipcMain.on('window:minimize', () => {
  if (mainWindow && !mainWindow.isDestroyed()) mainWindow.minimize()
})
ipcMain.on('window:toggle-maximize', () => {
  if (!mainWindow || mainWindow.isDestroyed()) return
  if (mainWindow.isMaximized()) mainWindow.unmaximize()
  else mainWindow.maximize()
})
ipcMain.on('window:close', () => {
  if (mainWindow && !mainWindow.isDestroyed()) mainWindow.close()
})
ipcMain.handle('window:is-maximized', () => {
  return !!(mainWindow && !mainWindow.isDestroyed() && mainWindow.isMaximized())
})

// ---------- 生命周期 ----------

const gotLock = app.requestSingleInstanceLock()
if (!gotLock) {
  app.quit()
} else {
  app.on('second-instance', () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore()
      mainWindow.focus()
    }
  })

  app.whenReady().then(async () => {
    createLoadingWindow()
    try {
      backendPort = await pickPort()
      backendProcess = spawnBackend(backendPort)
      await waitForHealth(backendPort)
      log(`Backend healthy on port ${backendPort}`)
      createMainWindow(backendPort)
    } catch (error) {
      log(`Startup failed: ${error}`)
      if (!isQuitting) {
        dialog.showErrorBox(
          'AI Comic Generator 启动失败',
          `${error.message || error}\n日志文件：${logFile()}`,
        )
        app.quit()
      }
    }
  })

  app.on('window-all-closed', () => {
    app.quit()
  })

  app.on('before-quit', () => {
    isQuitting = true
    killBackend()
  })

  process.on('exit', killBackend)
}
