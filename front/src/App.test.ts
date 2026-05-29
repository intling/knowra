import { mount } from "@vue/test-utils"
import { describe, expect, it } from "vitest"

import App from "./App.vue"

describe("App", () => {
  it("renders the active route in a full-screen app shell without a site header", () => {
    const wrapper = mount(App, {
      global: {
        stubs: {
          RouterLink: {
            template: "<a><slot /></a>",
          },
          RouterView: {
            template: '<div data-testid="router-view-stub" />',
          },
        },
      },
    })

    expect(wrapper.classes()).toContain("min-h-screen")
    expect(wrapper.find("header").exists()).toBe(false)
    expect(wrapper.find("main").exists()).toBe(false)
    expect(wrapper.find('[data-testid="router-view-stub"]').exists()).toBe(
      true,
    )
  })
})
