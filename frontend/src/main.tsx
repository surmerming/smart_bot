/** 入口（TSX 重构）：注册聊天 Widget 组件 + 渲染官网。 */
import "./styles.css";
import "./widget";
import { createRoot } from "react-dom/client";
import { Site } from "./site";

createRoot(document.getElementById("app") as HTMLElement).render(<Site />);
