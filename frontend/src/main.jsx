import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App.jsx";
import { loadStyleTheme, applyStyleTheme } from "./themes.js";
import "./index.css";

// 首屏前同步应用大风格主题：避免作用域样式（html[data-style-theme]）在首帧前未命中
applyStyleTheme(loadStyleTheme());

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
