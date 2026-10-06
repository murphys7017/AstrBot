import { assembleLocale } from "../../assembleLocale";

const modules = import.meta.glob("./**/*.json", {
  eager: true,
  import: "default",
});

export default assembleLocale(modules);
