"use strict";

const TYPE_COLORS = {
  concept: "#63e6be",
  property: "#fbbf24",
  relation: "#a78bfa",
  intent: "#60a5fa",
  construction: "#f472b6",
  user: "#f87171",
};

const TYPE_LABELS = {
  concept: "концепт",
  property: "свойство",
  relation: "отношение",
  intent: "намерение",
  construction: "конструкция",
  user: "пользователь",
};

const svg = d3.select("#graph");
const container = svg.append("g");
const linkLayer = container.append("g");
const nodeLayer = container.append("g");

let width = 800;
let height = 600;
let simulation = null;

const zoom = d3
  .zoom()
  .scaleExtent([0.15, 4])
  .on("zoom", (event) => container.attr("transform", event.transform));

svg.call(zoom);

function measure() {
  const rect = svg.node().getBoundingClientRect();
  width = Math.max(320, rect.width);
  height = Math.max(240, rect.height);
}

function colorFor(type) {
  return TYPE_COLORS[type] || "#8b98b8";
}

function radiusFor(node) {
  if (!node.active) return 8;
  return 10 + Math.min(1, node.activation) * 22;
}

function showError(message) {
  const box = document.getElementById("error");
  box.textContent = message;
  box.hidden = !message;
  if (message) {
    window.clearTimeout(showError._timer);
    showError._timer = window.setTimeout(() => {
      box.hidden = true;
    }, 5000);
  }
}

function updateStats(data) {
  const meta = data.meta || {};
  document.getElementById("stat-nodes").textContent = meta.node_count ?? 0;
  document.getElementById("stat-edges").textContent = meta.edge_count ?? 0;
  document.getElementById("stat-active").textContent = meta.active_count ?? 0;
  document.getElementById("stat-threshold").textContent =
    data.threshold ? data.threshold.toFixed(2) : "—";
  document.getElementById("stat-topk").textContent = data.top_k || "—";

  const query = document.getElementById("last-query");
  query.textContent = meta.last_query
    ? `активация от «${meta.last_query}»`
    : "нет активации";
}

function updateLegend(data) {
  const types = Array.from(new Set(data.nodes.map((node) => node.type)));
  const list = document.getElementById("legend");
  list.innerHTML = "";
  const ordered = types.length ? types : Object.keys(TYPE_LABELS);
  ordered.forEach((type) => {
    const item = document.createElement("li");
    const swatch = document.createElement("span");
    swatch.className = "swatch";
    swatch.style.background = colorFor(type);
    const label = document.createElement("span");
    label.textContent = TYPE_LABELS[type] || type;
    item.append(swatch, label);
    list.append(item);
  });
}

function render(data) {
  updateStats(data);
  updateLegend(data);
  document.getElementById("empty").hidden = data.nodes.length > 0;

  if (simulation) {
    simulation.stop();
    simulation = null;
  }
  linkLayer.selectAll("*").remove();
  nodeLayer.selectAll("*").remove();
  if (!data.nodes.length) return;

  const nodes = data.nodes.map((node) => ({ ...node }));
  const links = data.edges.map((edge) => ({ ...edge }));

  simulation = d3
    .forceSimulation(nodes)
    .force(
      "link",
      d3
        .forceLink(links)
        .id((node) => node.id)
        .distance((link) => 70 + (1 - link.weight) * 90)
        .strength(0.55)
    )
    .force("charge", d3.forceManyBody().strength(-320))
    .force("center", d3.forceCenter(width / 2, height / 2))
    .force(
      "collide",
      d3.forceCollide().radius((node) => radiusFor(node) + 20)
    )
    .force("x", d3.forceX(width / 2).strength(0.03))
    .force("y", d3.forceY(height / 2).strength(0.03));

  const link = linkLayer
    .selectAll("line")
    .data(links)
    .join("line")
    .attr("class", (edge) => (edge.active ? "link active" : "link"))
    .attr("stroke-width", (edge) => 1 + edge.weight * 4);

  link
    .append("title")
    .text(
      (edge) =>
        `${edge.relation} · вес ${edge.weight.toFixed(2)}${
          edge.label ? ` · ${edge.label}` : ""
        }`
    );

  const node = nodeLayer
    .selectAll("g")
    .data(nodes)
    .join("g")
    .attr("class", "node")
    .style("cursor", "pointer")
    .call(dragBehavior(simulation));

  node
    .append("circle")
    .attr("r", (item) => radiusFor(item))
    .attr("fill", (item) => colorFor(item.type))
    .attr("fill-opacity", (item) => (item.active ? 0.95 : 0.55))
    .attr("stroke", (item) => (item.active ? "#ffffff" : "rgba(10,15,30,0.9)"))
    .attr("stroke-width", (item) => (item.active ? 2.5 : 1.5))
    .append("title")
    .text(
      (item) =>
        `${item.name} · ${TYPE_LABELS[item.type] || item.type}` +
        (item.active ? ` · A=${item.activation.toFixed(2)}` : "")
    );

  node
    .append("text")
    .attr("class", "node-label")
    .attr("dy", (item) => radiusFor(item) + 14)
    .attr("text-anchor", "middle")
    .text((item) => item.name);

  let dragged = false;
  node.on("click", (event, item) => {
    if (dragged) {
      dragged = false;
      return;
    }
    event.stopPropagation();
    activate(item.name);
  });

  simulation.on("tick", () => {
    link
      .attr("x1", (edge) => edge.source.x)
      .attr("y1", (edge) => edge.source.y)
      .attr("x2", (edge) => edge.target.x)
      .attr("y2", (edge) => edge.target.y);

    node.attr(
      "transform",
      (item) => `translate(${item.x},${item.y})`
    );
  });

  function dragBehavior(sim) {
    return d3
      .drag()
      .on("start", (event, item) => {
        dragged = false;
        if (!event.active) sim.alphaTarget(0.25).restart();
        item.fx = item.x;
        item.fy = item.y;
      })
      .on("drag", (event, item) => {
        dragged = true;
        item.fx = event.x;
        item.fy = event.y;
      })
      .on("end", (event, item) => {
        if (!event.active) sim.alphaTarget(0);
        item.fx = null;
        item.fy = null;
      });
  }
}

async function fetchJson(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const body = await response.json();
      if (body.error) detail = body.error;
    } catch (ignored) {
      // тело не JSON — оставляем код
    }
    throw new Error(detail);
  }
  return response.json();
}

async function load(url = "/api/graph") {
  try {
    const data = await fetchJson(url);
    showError("");
    render(data);
  } catch (error) {
    showError(`Не удалось загрузить граф: ${error.message}`);
  }
}

async function activate(name) {
  const value = (name || "").trim();
  if (!value) return;
  try {
    const data = await fetchJson(
      `/api/activate?node=${encodeURIComponent(value)}`
    );
    showError("");
    render(data);
  } catch (error) {
    showError(`Узел не активирован: ${error.message}`);
  }
}

async function reset() {
  try {
    const data = await fetchJson("/api/reset", { method: "POST" });
    showError("");
    render(data);
  } catch (error) {
    showError(`Сброс не удался: ${error.message}`);
  }
}

document.getElementById("search-form").addEventListener("submit", (event) => {
  event.preventDefault();
  activate(document.getElementById("search-input").value);
});

document.getElementById("refresh").addEventListener("click", () => load());
document.getElementById("reset").addEventListener("click", () => reset());

window.addEventListener("resize", () => {
  measure();
  if (simulation) {
    simulation
      .force("center", d3.forceCenter(width / 2, height / 2))
      .force("x", d3.forceX(width / 2).strength(0.03))
      .force("y", d3.forceY(height / 2).strength(0.03))
      .alpha(0.3)
      .restart();
  }
});

measure();
load();
