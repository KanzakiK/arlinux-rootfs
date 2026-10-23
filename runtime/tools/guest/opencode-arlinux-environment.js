export default {
  id: "arlinux.environment",
  async setup(ctx) {
    await ctx.shell.hook("create.before", (event) => {
      event.env.NO_AT_BRIDGE = "0"
    })
  },
}
