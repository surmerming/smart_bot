/** 入口：注册聊天 Widget 组件 + 渲染官网。 */
import "./styles.css";
import "./widget";
import { renderSite } from "./site";

renderSite(document.getElementById("app") as HTMLElement);
