/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./vaultkeeper/web/templates/**/*.html"],
  plugins: [require("daisyui")],
  daisyui: {
    themes: ["night", "dark", "dim", "light", "winter", "nord"],
    logs: false,
  },
};
