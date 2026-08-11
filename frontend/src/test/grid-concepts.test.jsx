// ADR 0055：三个探索性视觉方向渲染（A 深夜书房 / B 编目抽屉 / C 展览橱窗）+ 开关
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import React from "react";
import { GridConceptA, GridConceptB, GridConceptC, GridConceptSwitcher, GRID_CONCEPTS, parseConcept } from "../components/GridConcepts.jsx";

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const ITEMS = [
  { id: 3, title: "命运石之门", type: "external_ref", source: "bangumi", chunks_count: 1 },
  { id: 5, title: "日常", type: "external_ref", source: "moegirl", chunks_count: 1 },
];

function coverOf() { return null; }

describe("三个方向渲染（真实数据，无封面走各自占位）", () => {
  it("A 深夜书房：concept-a + 编目号", () => {
    const { container } = render(<GridConceptA items={ITEMS} coverOf={coverOf} onOpenItem={() => {}} />);
    expect(container.querySelector('[data-concept="a"]')).toBeTruthy();
    expect(screen.getByText("NO.0003")).toBeTruthy();
    expect(screen.getByText("命运石之门")).toBeTruthy();
  });
  it("B 编目抽屉：concept-b + 索书卡式元数据行", () => {
    const { container } = render(<GridConceptB items={ITEMS} coverOf={coverOf} onOpenItem={() => {}} />);
    expect(container.querySelector('[data-concept="b"]')).toBeTruthy();
    expect(screen.getByText("NO.0003")).toBeTruthy();
    expect(screen.getByText("─ 编目号 0003")).toBeTruthy();
    expect(screen.getByText("─ 来源 bangumi")).toBeTruthy();
  });
  it("C 展览橱窗：concept-c + № 编号，宽/常规展示单元并存", () => {
    const { container } = render(<GridConceptC items={ITEMS} coverOf={coverOf} onOpenItem={() => {}} />);
    expect(container.querySelector('[data-concept="c"]')).toBeTruthy();
    expect(screen.getAllByText(/№ 000/).length).toBeGreaterThan(0);
  });
  it("三个方向数据标注不同（互相是不同概念容器）", () => {
    const a = render(<GridConceptA items={ITEMS} coverOf={coverOf} onOpenItem={() => {}} />);
    expect(a.container.querySelector('[data-concept="a"]')).toBeTruthy();
    cleanup();
    const b = render(<GridConceptB items={ITEMS} coverOf={coverOf} onOpenItem={() => {}} />);
    expect(b.container.querySelector('[data-concept="b"]')).toBeTruthy();
  });
});

describe("方向开关", () => {
  it("渲染 4 项（classic + A/B/C），点击触发 onChange", () => {
    const onChange = vi.fn();
    render(<GridConceptSwitcher value="classic" onChange={onChange} />);
    expect(GRID_CONCEPTS.length).toBe(4);
    fireEvent.click(screen.getByText("B 编目抽屉"));
    expect(onChange).toHaveBeenCalledWith("b");
  });
  it("parseConcept 校验合法值，非法回 null", () => {
    expect(parseConcept("a")).toBe("a");
    expect(parseConcept("c")).toBe("c");
    expect(parseConcept("x")).toBeNull();
  });
});
