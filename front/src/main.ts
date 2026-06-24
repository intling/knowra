import { createPinia } from "pinia"
import { createApp } from "vue"

import App from "./App.vue"
import router from "./router"
import "./style.css"
import { initLogger, createLogger, getRingBuffer } from "./shared/logger"

// Initialize the logging subsystem (reads Vite env vars, sets up ring buffer, etc.).
initLogger()

const app = createApp(App)

// --- Vue global error handler (Task 14.1) ---
const appLogger = createLogger("app:vue", getRingBuffer())
app.config.errorHandler = (err, _instance, info) => {
  const message = `Vue 组件错误 (${info})`
  if (err instanceof Error) {
    appLogger.error(message, err, { componentInfo: info })
  } else {
    appLogger.error(message, undefined, { componentInfo: info, error: String(err) })
  }
}

// --- Unhandled Promise rejection handler (Task 14.2) ---
window.addEventListener("unhandledrejection", (event) => {
  const reason = event.reason
  if (reason instanceof Error) {
    appLogger.error("未捕获的 Promise 拒绝", reason)
  } else {
    appLogger.error("未捕获的 Promise 拒绝", undefined, { reason: String(reason) })
  }
})

app.use(createPinia())
app.use(router)
app.mount("#app")
