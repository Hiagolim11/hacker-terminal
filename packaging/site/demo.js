/* Interactive demo of Hacker Terminal for the project site.
 *
 * A small simulated zsh inside a window drawn like the GTK app. The themes,
 * profiles, quick actions and keyboard sound packs are the app's own: they come
 * from packaging/build_site.py as JSON (#demo-data), so the demo never drifts
 * from the release. Nothing here runs on the visitor's computer.
 */
(() => {
  "use strict";

  const host = document.getElementById("demo");
  const dataNode = document.getElementById("demo-data");
  if (!host || !dataNode) return;
  const DATA = JSON.parse(dataNode.textContent);
  const THEMES = new Map(DATA.themes.map((theme) => [theme.id, theme]));
  const PROFILES = new Map(DATA.profiles.map((profile) => [profile.id, profile]));
  const PACKS = new Map(DATA.soundpacks.map((pack) => [pack.id, pack]));
  const VERSION = DATA.version;
  const REDUCED_MOTION = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const HOME = "/home/hacker";
  const USER = "hacker";
  const HOST = "lab";

  const FONTS = [
    { name: "JetBrains Mono", css: '"JetBrains Mono", "Geist Mono", monospace', scale: 1 },
    { name: "Geist Mono", css: '"Geist Mono", "JetBrains Mono", monospace', scale: 1 },
    { name: "IBM Plex Mono", css: '"IBM Plex Mono", "JetBrains Mono", monospace', scale: 1 },
    { name: "VT323", css: '"VT323", "JetBrains Mono", monospace', scale: 1.38 },
  ];
  // Fonts the themes suggest, mapped to the closest web font this page loads.
  const WEB_FONT_FOR = { Terminus: "VT323", VT323: "VT323", "IBM 3270": "IBM Plex Mono" };
  const CURSORS = { block: "Bloco", ibeam: "Barra", underline: "Sublinhado" };

  const SHORTCUTS = [
    ["Nova aba", "Ctrl+Shift+T"], ["Fechar painel ou aba", "Ctrl+Shift+W"],
    ["Dividir horizontalmente", "Ctrl+Shift+D"], ["Dividir verticalmente", "Ctrl+Shift+E"],
    ["Alternar painel dividido", "Ctrl+Shift+O"], ["Digitar em todos os painéis da aba", "Ctrl+Shift+I"],
    ["Próxima aba", "Ctrl+PageDown"], ["Aba anterior", "Ctrl+PageUp"],
    ["Ir ao prompt anterior", "Ctrl+Shift+↑"], ["Ir ao próximo prompt", "Ctrl+Shift+↓"],
    ["Copiar saída do último comando", "Ctrl+Shift+L"], ["Copiar", "Ctrl+Shift+C"], ["Colar", "Ctrl+Shift+V"],
    ["Paleta de comandos", "Ctrl+Shift+P"], ["Histórico de comandos", "Ctrl+Shift+H"],
    ["Mostrar ou ocultar ações", "Ctrl+Shift+B"], ["Preferências", "Ctrl+,"],
    ["Aumentar fonte", "Ctrl++"], ["Diminuir fonte", "Ctrl+-"], ["Tamanho padrão da fonte", "Ctrl+0"], ["Tela cheia", "F11"],
  ];

  const state = {
    profile: "",
    theme: THEMES.has("zero-day") ? "zero-day" : DATA.default_theme,
    font: "JetBrains Mono",
    fontSize: 11,
    effects: true,
    sound: false,
    pack: DATA.soundpacks.length ? DATA.soundpacks[0].id : "",
    volume: 70,
    keyRelease: true,
    panel: false,
    cursor: "block",
    blink: true,
    marks: true,
  };

  /* ---------- small helpers ---------- */

  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const normalize = (text) => text.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
  const pad = (text, width) => String(text) + " ".repeat(Math.max(0, width - String(text).length));
  const padStart = (text, width) => " ".repeat(Math.max(0, width - String(text).length)) + String(text);

  function el(tag, attrs = {}, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs)) {
      if (value === false || value == null) continue;
      if (key === "class") node.className = value;
      else if (key === "text") node.textContent = value;
      else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
      else if (key === "style") node.style.cssText = value;
      else node.setAttribute(key, value === true ? "" : value);
    }
    for (const child of children.flat()) {
      if (child == null || child === false) continue;
      node.append(child instanceof Node ? child : document.createTextNode(String(child)));
    }
    return node;
  }

  function rgb(hex) {
    return [1, 3, 5].map((index) => parseInt(hex.slice(index, index + 2), 16));
  }
  function mix(color, base, amount) {  // same blend as themes._mix
    const a = rgb(color);
    const b = rgb(base);
    return "#" + a.map((top, i) => Math.round(top * amount + b[i] * (1 - amount)).toString(16).padStart(2, "0")).join("");
  }
  function luminance(hex) {
    const [r, g, b] = rgb(hex).map((v) => {
      const c = v / 255;
      return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
    });
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  }
  function contrast(a, b) {
    const [x, y] = [luminance(a), luminance(b)].sort((m, n) => n - m);
    return (x + 0.05) / (y + 0.05);
  }
  function hash(text) {
    let h = 2166136261;
    for (const char of text) h = Math.imul(h ^ char.charCodeAt(0), 16777619);
    return h >>> 0;
  }
  function shellQuote(value) {  // shlex.quote
    if (!value) return "''";
    return /^[\w@%+=:,./-]+$/.test(value) ? value : "'" + value.replace(/'/g, "'\"'\"'") + "'";
  }
  function reveal(container, item) {  // scroll a list to an item without moving the page
    if (!item) return;
    const top = item.offsetTop;
    const bottom = top + item.offsetHeight;
    if (top < container.scrollTop) container.scrollTop = top;
    else if (bottom > container.scrollTop + container.clientHeight) container.scrollTop = bottom - container.clientHeight;
  }
  function copyText(text) {
    if (navigator.clipboard) return navigator.clipboard.writeText(text).then(() => true, () => false);
    return Promise.resolve(false);
  }
  function findTheme(query) {
    if (!query) return null;
    const wanted = normalize(query);
    if (THEMES.has(wanted)) return THEMES.get(wanted);
    const all = [...THEMES.values()];
    return all.find((t) => normalize(t.name) === wanted)
      || all.find((t) => t.id.startsWith(wanted) || normalize(t.name).startsWith(wanted))
      || all.find((t) => t.id.includes(wanted) || normalize(t.name).includes(wanted)) || null;
  }
  function findProfile(query) {
    if (!query) return null;
    const wanted = normalize(query);
    const all = [...PROFILES.values()];
    return PROFILES.get(wanted) || all.find((p) => normalize(p.name) === wanted)
      || all.find((p) => normalize(p.name).startsWith(wanted) || p.id.startsWith(wanted)) || null;
  }
  const fontInfo = (name) => FONTS.find((font) => font.name === name) || FONTS[0];
  const currentTheme = () => THEMES.get(state.theme);

  /* ---------- quick action placeholders (port of actions.scan/fill) ---------- */

  const PLACEHOLDER = /\{([A-Za-z_À-ɏ][\wÀ-ɏ-]{0,31})(?:=([^{}'"\n]*))?\}/y;
  function scanFields(command) {
    const found = [];
    let mode = "plain";
    for (let i = 0; i < command.length; i += 1) {
      const char = command[i];
      if (mode === "single") { if (char === "'") mode = "plain"; continue; }
      if (char === "\\") { i += 1; continue; }
      if (char === "'" && mode === "plain") { mode = "single"; continue; }
      if (char === '"') { mode = mode === "double" ? "plain" : "double"; continue; }
      if (char === "{" && (i === 0 || command[i - 1] !== "$")) {
        PLACEHOLDER.lastIndex = i;
        const match = PLACEHOLDER.exec(command);
        if (match) {
          found.push({ start: i, end: PLACEHOLDER.lastIndex, name: match[1], fallback: match[2], mode });
          i = PLACEHOLDER.lastIndex - 1;
        }
      }
    }
    return found;
  }
  function fillFields(command, values) {
    let result = "";
    let last = 0;
    for (const field of scanFields(command)) {
      let value = values[field.name] || field.fallback || "";
      if (field.mode === "double") value = value.replace(/[\\"$`]/g, "\\$&");
      else value = value ? shellQuote(value) : "";
      result += command.slice(last, field.start) + value;
      last = field.end;
    }
    return result + command.slice(last);
  }

  /* ---------- the virtual file system ---------- */

  const dir = (children = {}) => ({ type: "dir", children });
  const file = (content, extra = {}) => ({ type: "file", content, ...extra });
  const exe = (content) => file(content, { exec: true });
  const image = (url) => file("", { image: url });
  const source = (name) => file(`# ${name}\n# O código completo está em https://github.com/Hiagolim11/hacker-terminal\n`);

  function themeIni(theme) {
    const lines = ["[theme]", `id = ${theme.id}`, `name = ${theme.name}`, `author = ${theme.author}`];
    if (theme.font) lines.push(`font = ${theme.font}`);
    lines.push("", "[interface]", ...Object.entries(theme.ui).map(([k, v]) => `${k} = ${v}`));
    lines.push("", "[terminal]", ...Object.entries(theme.term).map(([k, v]) => `${k} = ${v}`), `ansi = ${theme.ansi.join(", ")}`);
    lines.push("", "[effects]", `matrix_color = ${theme.fx.matrix}`, `scanline_opacity = ${theme.fx.scanlines}`);
    for (const key of ["glow", "vignette", "noise", "flicker", "curvature"]) if (theme.fx[key]) lines.push(`${key} = ${theme.fx[key]}`);
    lines.push(`rain = ${theme.fx.rain}`);
    return lines.join("\n") + "\n";
  }
  function configIni() {
    return [
      "[terminal]",
      `profile = ${state.profile}`,
      `theme = ${state.theme}`,
      `font = ${state.font}`,
      `font_size = ${state.fontSize}`,
      `effects = ${state.effects}`,
      `sound = ${state.sound}`,
      "scrollback_lines = 20000",
      `panel_visible = ${state.panel}`,
      "restore_session = true",
      `cursor_shape = ${state.cursor}`,
      `cursor_blink = ${state.blink ? "on" : "off"}`,
      "opacity = 100",
      "shell = ",
      "shell_integration = true",
      `command_marks = ${state.marks}`,
      "notify_commands = true",
      "notify_after = 10",
      "command_history = true",
      `key_switch = pack:${state.pack}`,
      `key_volume = ${state.volume}`,
      `key_release = ${state.keyRelease}`,
      "",
    ].join("\n");
  }
  function actionsIni() {
    return DATA.actions.map((action, order) => [
      `[action:${action.id}]`, `order = ${order}`, `label = ${action.label}`, `command = ${action.command}`,
      "confirm = false", `in_terminal = ${action.in_terminal}`, "",
    ].join("\n")).join("\n");
  }

  const SCREENSHOTS = ["background-image", "grid", "hero", "history", "modern-themes", "palette", "phosphor", "phosphor-amber",
    "prefs-general", "prefs-shortcuts", "prefs-sound", "split", "ssh", "theme-editor", "themes", "viewer-sheet"];
  const PY_FILES = ["__init__", "actions", "app", "background", "cli", "config", "connections", "constants", "documents", "dropdown",
    "effects", "fonts", "history", "inline_image", "keysound", "launcher", "logs", "openserver", "passwords", "profiles", "project",
    "runtime", "sandbox", "session", "shortcuts", "terminal", "themes", "viewer"];

  const fs = dir({
    home: dir({
      hacker: dir({
        "hacker-terminal": dir({
          assets: dir({ "hacker-terminal.svg": file("<svg …/>\n"), "org.hackerterminal.HackerTerminal.desktop": file("[Desktop Entry]\nName=Hacker Terminal\nExec=hacker-terminal\nIcon=hacker-terminal\nType=Application\nCategories=System;TerminalEmulator;\n") }),
          bin: dir({ "ht-open": exe("#!/bin/sh\n# abre imagens e planilhas numa aba do Hacker Terminal\n"), "ht-askpass": exe("#!/bin/sh\n"), "ht-copy-key": exe("#!/bin/sh\n") }),
          docs: dir({
            "index.html": file("<!doctype html>\n<title>Hacker Terminal</title>\n<!-- esta página -->\n"),
            screenshots: dir(Object.fromEntries(SCREENSHOTS.map((name) => [`${name}.png`, image(`screenshots/${name}.png`)]))),
          }),
          hackerterminal: dir({
            ...Object.fromEntries(PY_FILES.map((name) => [`${name}.py`, source(`${name}.py`)])),
            dialogs: dir(Object.fromEntries(["actions", "common", "editors", "history", "palette", "preferences", "result", "ssh"].map((n) => [`${n}.py`, source(`${n}.py`)]))),
            window: dir(Object.fromEntries(["commands", "dropdown", "main", "output", "panel", "panes", "ssh", "viewer"].map((n) => [`${n}.py`, source(`${n}.py`)]))),
            themes: dir(Object.fromEntries([...THEMES.values()].map((theme) => [`${theme.id}.ini`, file(themeIni(theme))]))),
            soundpacks: dir(Object.fromEntries(DATA.soundpacks.map((pack) => [pack.id, dir({ "config.json": file(`{\n  "name": "${pack.name}",\n  "key_define_type": "multi"\n}\n`) })]))),
          }),
          packaging: dir({ "build-deb.sh": exe("#!/bin/sh\n"), "build_site.py": exe("#!/usr/bin/env python3\n\"\"\"Gera docs/index.html (este site) a partir do próprio app.\"\"\"\n") }),
          tests: dir({ "smoke.sh": exe("#!/bin/sh\n"), "test_core.py": source("test_core.py") }),
          "AUDIT.md": file("# Auditoria\n"),
          "CHANGELOG.md": file(`# Novidades\n\n## ${VERSION}\n\n- Prévia ao vivo dos temas na paleta de comandos: o tema aparece na hora e volta ao anterior se você fechar sem escolher.\n- Diálogos de tema com botões claros; a janela de resultado das ações cresce com a saída.\n`),
          "CONTRIBUTING.md": file("# Como contribuir\n\nRode `make check` antes de abrir um pull request.\n"),
          "hacker_terminal.py": exe("#!/usr/bin/env python3\nfrom hackerterminal.app import main\n\nraise SystemExit(main())\n"),
          "install.sh": exe("#!/bin/sh\n# instala em ~/.local, só para a sua conta\n"),
          LICENSE: file("MIT License\n\nCopyright (c) Hacker Terminal\n"),
          Makefile: file(".PHONY: run diagnose check check-gui deb\n\nrun:\n\t./run.sh\n\ndiagnose:\n\t./run.sh --diagnose\n\ncheck:\n\t./tests/smoke.sh\n\ndeb:\n\t./packaging/build-deb.sh \"$(DEB_OUTPUT_DIR)\"\n"),
          "README.md": file("# Hacker Terminal\n\nUm terminal nativo para Linux, rápido e totalmente personalizável — com alma retrô.\n\nGTK 3 · VTE · Python · sem Electron, sem navegador, sem telemetria\n"),
          "run.sh": exe("#!/bin/sh\nexec python3 \"$(dirname \"$0\")/hacker_terminal.py\" \"$@\"\n"),
        }),
        labs: dir({
          "alvos.txt": file("# só alvos com autorização por escrito\n10.0.0.5\n10.0.0.7\nscanme.nmap.org\n"),
          "notas.md": file("# Notas do laboratório\n\n- [x] instalar o Hacker Terminal\n- [x] escolher um tema Fósforo\n- [ ] ligar o som do Holy Pandas\n"),
          "scan.sh": exe("#!/bin/sh\nnmap -sV \"$1\"\n"),
        }),
        ".ssh": dir({ config: file("Host lab\n  HostName 10.0.0.5\n  User hacker\n"), "id_ed25519.pub": file("ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI… hacker@lab\n"), known_hosts: file("") }),
        ".config": dir({
          "hacker-terminal": dir({
            "config.ini": file(configIni),
            "actions.ini": file(actionsIni),
            profiles: dir({}),
            themes: dir({}),
          }),
        }),
        ".zshrc": file("# o Hacker Terminal lê o seu .zshrc normalmente\nautoload -U compinit && compinit\nsource ~/.zsh/zsh-autosuggestions.zsh\n"),
      }),
    }),
    usr: dir({ bin: dir({}) }),
    etc: dir({ hostname: file("lab\n"), "os-release": file('PRETTY_NAME="Kali GNU/Linux Rolling"\nNAME="Kali GNU/Linux"\nID=kali\n') }),
    tmp: dir({}),
  });

  function resolvePath(cwd, path) {
    if (!path) return cwd;
    if (path === "~" || path.startsWith("~/")) path = HOME + path.slice(1);
    const parts = (path.startsWith("/") ? path : `${cwd}/${path}`).split("/");
    const out = [];
    for (const part of parts) {
      if (!part || part === ".") continue;
      if (part === "..") out.pop(); else out.push(part);
    }
    return "/" + out.join("/");
  }
  function lookup(path) {
    let node = fs;
    for (const part of path.split("/").filter(Boolean)) {
      if (node.type !== "dir" || !Object.hasOwn(node.children, part)) return null;
      node = node.children[part];
    }
    return node;
  }
  function parentOf(path) {
    const index = path.lastIndexOf("/");
    return { dir: lookup(path.slice(0, index) || "/"), name: path.slice(index + 1) };
  }
  const readFile = (node) => (typeof node.content === "function" ? node.content() : node.content);
  const shortPath = (path) => (path === HOME ? "~" : path.startsWith(HOME + "/") ? "~" + path.slice(HOME.length) : path);
  const inRepo = (path) => path === `${HOME}/hacker-terminal` || path.startsWith(`${HOME}/hacker-terminal/`);
  const sizeOf = (node) => (node.type === "dir" ? 4096 : node.image ? 180000 + (hash(node.image) % 90000) : new TextEncoder().encode(readFile(node)).length);
  function nameClass(name, node) {
    if (node.type === "dir") return "c4 b";
    if (node.exec) return "c2 b";
    if (node.image) return "c5 b";
    return "";
  }

  /* ---------- shell parsing ---------- */

  // Words keep their quoting so variables expand only when the command runs.
  function lex(line) {
    const tokens = [];
    let word = null;
    let i = 0;
    const part = (text, quote) => {
      if (!word) word = { type: "word", parts: [] };
      word.parts.push({ text, quote });
    };
    const flush = () => { if (word) tokens.push(word); word = null; };
    while (i < line.length) {
      const char = line[i];
      if (char === " " || char === "\t") { flush(); i += 1; continue; }
      if (char === "#" && !word) break;
      if (char === "'") {
        const end = line.indexOf("'", i + 1);
        if (end < 0) throw new Error("aspas sem fechamento");
        part(line.slice(i + 1, end), "single");
        i = end + 1;
        continue;
      }
      if (char === '"') {
        let text = "";
        i += 1;
        while (i < line.length && line[i] !== '"') {
          if (line[i] === "\\" && i + 1 < line.length && '"\\$`'.includes(line[i + 1])) { text += line[i + 1]; i += 2; continue; }
          text += line[i];
          i += 1;
        }
        if (i >= line.length) throw new Error("aspas sem fechamento");
        part(text, "double");
        i += 1;
        continue;
      }
      if (char === "\\") { part(line[i + 1] || "", "single"); i += 2; continue; }
      const two = line.slice(i, i + 2);
      if (two === "&&" || two === "||") { flush(); tokens.push({ type: "op", value: two }); i += 2; continue; }
      if (char === ";" || char === "|" || char === "&") { flush(); tokens.push({ type: "op", value: char === "&" ? ";" : char }); i += 1; continue; }
      if (char === ">" || (char === "<")) {
        let fd = 1;
        if (word && word.parts.length === 1 && word.parts[0].quote === "none" && /^[12]$/.test(word.parts[0].text)) { fd = Number(word.parts[0].text); word = null; }
        flush();
        if (char === "<") { tokens.push({ type: "redir", fd: 0, append: false }); i += 1; continue; }
        let append = false;
        i += 1;
        if (line[i] === ">") { append = true; i += 1; }
        if (line.slice(i, i + 2) === "&1") { tokens.push({ type: "dup", fd }); i += 2; continue; }
        tokens.push({ type: "redir", fd, append });
        continue;
      }
      let text = "";
      while (i < line.length && !" \t'\"\\;|&<>".includes(line[i])) { text += line[i]; i += 1; }
      part(text, "none");
    }
    flush();
    return tokens;
  }

  // [{op, pipeline: [{words, redirects}]}]
  function parse(tokens) {
    const list = [];
    let pipeline = [];
    let command = { words: [], redirects: [] };
    let op = ";";
    const endCommand = () => {
      if (!command.words.length && !command.redirects.length) throw new Error("erro de sintaxe perto de um operador");
      pipeline.push(command);
      command = { words: [], redirects: [] };
    };
    for (let index = 0; index < tokens.length; index += 1) {
      const token = tokens[index];
      if (token.type === "word") command.words.push(token);
      else if (token.type === "redir") {
        const target = tokens[index + 1];
        if (!target || target.type !== "word") throw new Error("erro de sintaxe perto de '>'");
        command.redirects.push({ fd: token.fd, append: token.append, target });
        index += 1;
      } else if (token.type === "dup") command.redirects.push({ fd: token.fd, dup: true });
      else if (token.value === "|") endCommand();
      else {
        if (!command.words.length && !pipeline.length && token.value === ";" && !list.length) continue;
        endCommand();
        list.push({ op, pipeline });
        pipeline = [];
        op = token.value;
      }
    }
    if (command.words.length || command.redirects.length) { pipeline.push(command); list.push({ op, pipeline }); }
    else if (pipeline.length || op !== ";") throw new Error("erro de sintaxe: comando incompleto");
    return list;
  }

  function expandWord(word, session) {
    let text = "";
    let globbing = false;
    word.parts.forEach((piece, index) => {
      let value = piece.text;
      if (piece.quote === "single") { text += value; return; }
      if (piece.quote === "none" && index === 0 && (value === "~" || value.startsWith("~/"))) value = HOME + value.slice(1);
      value = value.replace(/\$(\?|\{[A-Za-z_]\w*\}|[A-Za-z_]\w*)/g, (_m, name) => {
        name = name.replace(/[{}]/g, "");
        if (name === "?") return String(session.lastCode);
        if (name === "PWD") return session.cwd;
        return session.env[name] ?? "";
      });
      if (piece.quote === "none" && /[*?]/.test(value)) globbing = true;
      text += value;
    });
    if (!globbing) return [text];
    const slash = text.lastIndexOf("/");
    const base = slash >= 0 ? text.slice(0, slash + 1) : "";
    const pattern = text.slice(slash + 1);
    const folder = lookup(resolvePath(session.cwd, base || "."));
    if (!folder || folder.type !== "dir") return [text];
    const regex = new RegExp("^" + pattern.replace(/[.+^${}()|[\]\\]/g, "\\$&").replace(/\*/g, ".*").replace(/\?/g, ".") + "$");
    const matches = Object.keys(folder.children).filter((name) => regex.test(name) && (pattern.startsWith(".") || !name.startsWith("."))).sort();
    return matches.length ? matches.map((name) => base + name) : [text];
  }

  /* ---------- output sinks ---------- */

  // A sink receives text (with "\n") plus an optional class or inline style.
  class Collector {
    constructor() { this.text = ""; }
    write(text) { this.text += text; }
  }
  class FileSink extends Collector {
    constructor(path, append) { super(); this.path = path; this.append = append; }
    close() {
      const { dir: folder, name } = parentOf(this.path);
      if (!folder || folder.type !== "dir") return false;
      const existing = folder.children[name];
      if (existing && existing.type === "dir") return false;
      const before = this.append && existing && typeof existing.content === "string" ? existing.content : "";
      folder.children[name] = file(before + this.text);
      return true;
    }
  }
  const NULL_SINK = { write() {} };

  /* ---------- commands ---------- */

  const COMMANDS = {};
  const HELP_GROUPS = [
    ["Arquivos", "ls cd pwd cat tree head tail grep wc sort echo printf touch mkdir rm"],
    ["Sistema", "whoami hostname uname date uptime ps df free ip ss ping nmap history clear sleep exit"],
    ["Projeto", "git neofetch ht-open hacker-terminal"],
  ];
  const def = (names, fn) => names.split(" ").forEach((name) => { COMMANDS[name] = fn; });
  const out = (ctx, text = "", cls, style) => ctx.out.write(text + "\n", cls, style);
  const fail = (ctx, text, code = 1) => { ctx.err.write(text + "\n", "c1"); return code; };
  const flags = (args) => args.filter((a) => /^-[^-]/.test(a)).join("").replace(/-/g, "");

  def("help ajuda", (ctx) => {
    out(ctx, `Hacker Terminal ${VERSION} — demonstração no navegador (um zsh simulado)`, "b");
    out(ctx);
    for (const [title, names] of HELP_GROUPS) {
      ctx.out.write(pad(`  ${title}`, 14), "c3");
      out(ctx, names.split(" ").join("  "));
    }
    out(ctx);
    out(ctx, "  Aparência", "c3");
    const rows = [
      ["tema [nome]", `troca o tema (${THEMES.size} internos); sem nome, lista todos`],
      ["perfil [nome]", "aplica um perfil: " + [...PROFILES.keys()].join(", ")],
      ["efeitos on|off", "brilho, scanlines, chuva digital e curvatura CRT"],
      ["fonte N|+|-|nome", "tamanho ou família da fonte"],
      ["cursor bloco|barra|sublinhado", "formato do cursor"],
      ["som on|off|pacote", "som de teclado mecânico (gravações reais)"],
      ["painel", "mostra ou oculta as ações rápidas"],
      ["cores", "as 16 cores ANSI do tema"],
      ["matrix", "chuva digital na tela toda (qualquer tecla sai)"],
    ];
    for (const [name, text] of rows) { ctx.out.write("    " + pad(name, 30), "c2"); out(ctx, text, "dim"); }
    out(ctx);
    out(ctx, "  Atalhos", "c3");
    out(ctx, "    Ctrl+Shift+P paleta · Ctrl+, preferências · Ctrl+Shift+B ações · Ctrl+Shift+D/E dividir", "dim");
    out(ctx, "    Ctrl+Shift+O próximo painel · Ctrl+Shift+I digitar em todos · Ctrl+Shift+H histórico", "dim");
    out(ctx, "    Ctrl+Shift+↑/↓ pular entre comandos · Ctrl+Shift+L copiar a última saída · Tab completa", "dim");
    return 0;
  });

  def("pwd", (ctx) => { out(ctx, ctx.session.cwd); return 0; });

  def("cd", (ctx) => {
    const target = ctx.args[0] === "-" ? ctx.session.oldCwd || ctx.session.cwd : resolvePath(ctx.session.cwd, ctx.args[0] || HOME);
    const node = lookup(target);
    if (!node) return fail(ctx, `cd: arquivo ou diretório inexistente: ${ctx.args[0]}`);
    if (node.type !== "dir") return fail(ctx, `cd: não é um diretório: ${ctx.args[0]}`);
    ctx.session.oldCwd = ctx.session.cwd;
    ctx.session.cwd = target;
    return 0;
  });

  function columns(ctx, items) {
    const width = ctx.session.columns ? ctx.session.columns() : 80;
    if (!ctx.tty || !items.length) { items.forEach(([name, cls]) => out(ctx, name, ctx.tty ? cls : undefined)); return; }
    const longest = Math.max(...items.map(([name]) => name.length)) + 2;
    const perRow = Math.max(1, Math.floor(width / longest));
    const rows = Math.ceil(items.length / perRow);
    for (let r = 0; r < rows; r += 1) {
      for (let c = 0; c < perRow; c += 1) {
        const item = items[c * rows + r];
        if (!item) continue;
        ctx.out.write(item[0], item[1]);
        if (items[(c + 1) * rows + r]) ctx.out.write(" ".repeat(longest - item[0].length));
      }
      ctx.out.write("\n");
    }
  }
  def("ls dir", (ctx) => {
    const opts = flags(ctx.args);
    const all = opts.includes("a");
    const long = opts.includes("l");
    const paths = ctx.args.filter((a) => !a.startsWith("-"));
    let code = 0;
    const targets = paths.length ? paths : ["."];
    targets.forEach((path, index) => {
      const full = resolvePath(ctx.session.cwd, path);
      const node = lookup(full);
      if (!node) { code = fail(ctx, `ls: não foi possível acessar '${path}': Arquivo ou diretório inexistente`, 2); return; }
      let entries = node.type === "dir"
        ? Object.entries(node.children).filter(([name]) => all || !name.startsWith(".")).sort(([a], [b]) => a.replace(/^\./, "").localeCompare(b.replace(/^\./, ""), "pt"))
        : [[path, node]];
      if (all && node.type === "dir") entries = [[".", node], ["..", lookup(resolvePath(full, "..")) || node], ...entries];
      if (targets.length > 1 && node.type === "dir") { if (index) out(ctx); out(ctx, `${path}:`); }
      if (long) {
        if (node.type === "dir") out(ctx, `total ${entries.length * 4}`);
        for (const [name, child] of entries) {
          const perms = child.type === "dir" ? "drwxr-xr-x" : child.exec ? "-rwxr-xr-x" : "-rw-r--r--";
          const links = child.type === "dir" ? Object.keys(child.children).filter((n) => lookup(`${full}/${n}`)?.type === "dir").length + 2 : 1;
          ctx.out.write(`${perms} ${padStart(links, 2)} ${USER} ${USER} ${padStart(sizeOf(child), 6)} out 17 14:43 `);
          out(ctx, name, ctx.tty ? nameClass(name, child) : undefined);
        }
      } else columns(ctx, entries.map(([name, child]) => [name, nameClass(name, child)]));
    });
    return code;
  });

  def("tree", (ctx) => {
    const depthIndex = ctx.args.indexOf("-L");
    const maxDepth = depthIndex >= 0 ? Number(ctx.args[depthIndex + 1]) || 1 : 3;
    const path = ctx.args.find((a, i) => !a.startsWith("-") && i !== depthIndex + 1) || ".";
    const root = lookup(resolvePath(ctx.session.cwd, path));
    if (!root || root.type !== "dir") return fail(ctx, `${path} [error opening dir]`, 2);
    let dirs = 0;
    let files = 0;
    out(ctx, path, "c4 b");
    const walk = (node, prefix, depth) => {
      const entries = Object.entries(node.children).filter(([n]) => !n.startsWith(".")).sort(([a], [b]) => a.localeCompare(b, "pt"));
      entries.forEach(([name, child], index) => {
        const last = index === entries.length - 1;
        ctx.out.write(prefix + (last ? "└── " : "├── "));
        out(ctx, name, nameClass(name, child));
        if (child.type === "dir") { dirs += 1; if (depth < maxDepth) walk(child, prefix + (last ? "    " : "│   "), depth + 1); }
        else files += 1;
      });
    };
    walk(root, "", 1);
    out(ctx);
    out(ctx, `${dirs} directories, ${files} files`);
    return 0;
  });

  function readInputs(ctx, name) {
    const paths = ctx.args.filter((a) => !/^-\w/.test(a));
    if (!paths.length) return ctx.stdin == null ? [] : [{ text: ctx.stdin }];
    return paths.map((path) => {
      const node = lookup(resolvePath(ctx.session.cwd, path));
      if (!node) return { error: `${name}: ${path}: Arquivo ou diretório inexistente` };
      if (node.type === "dir") return { error: `${name}: ${path}: É um diretório` };
      if (node.image) return { text: `\u0089PNG\n(imagem binária: use ht-open ${path})\n` };
      return { text: readFile(node) };
    });
  }
  def("cat less more bat", (ctx) => {
    let code = 0;
    for (const input of readInputs(ctx, ctx.name)) {
      if (input.error) code = fail(ctx, input.error);
      else ctx.out.write(input.text);
    }
    return code;
  });
  const linesOf = (text) => text.replace(/\n$/, "").split("\n");
  function countArg(ctx, fallback) {
    const index = ctx.args.findIndex((a) => a === "-n" || /^-\d+$/.test(a));
    if (index < 0) return fallback;
    const value = ctx.args[index] === "-n" ? ctx.args.splice(index, 2)[1] : ctx.args.splice(index, 1)[0].slice(1);
    return Math.max(0, Number(value) || 0);
  }
  def("head tail", (ctx) => {
    const count = countArg(ctx, 10);
    let code = 0;
    for (const input of readInputs(ctx, ctx.name)) {
      if (input.error) { code = fail(ctx, input.error); continue; }
      const lines = linesOf(input.text);
      const picked = ctx.name === "head" ? lines.slice(0, count) : lines.slice(-count || lines.length);
      if (input.text) ctx.out.write(picked.join("\n") + "\n");
    }
    return code;
  });
  def("grep", (ctx) => {
    const opts = flags(ctx.args);
    const rest = ctx.args.filter((a) => !/^-\w/.test(a));
    const pattern = rest.shift();
    if (pattern == null) return fail(ctx, "Uso: grep [OPÇÃO]... PADRÕES [ARQUIVO]...", 2);
    let regex;
    try { regex = new RegExp(pattern, opts.includes("i") ? "i" : ""); } catch { return fail(ctx, "grep: expressão regular inválida", 2); }
    ctx.args = rest;
    let found = false;
    let code = 0;
    for (const input of readInputs(ctx, "grep")) {
      if (input.error) { code = 2; fail(ctx, input.error, 2); continue; }
      for (const line of linesOf(input.text)) {
        if (regex.test(line) === opts.includes("v")) continue;
        found = true;
        const match = !opts.includes("v") && ctx.tty && line.match(regex);
        if (match && match[0]) {
          ctx.out.write(line.slice(0, match.index));
          ctx.out.write(match[0], "c1 b");
          out(ctx, line.slice(match.index + match[0].length));
        } else out(ctx, line);
      }
    }
    return code || (found ? 0 : 1);
  });
  def("wc", (ctx) => {
    const opts = flags(ctx.args);
    for (const input of readInputs(ctx, "wc")) {
      if (input.error) return fail(ctx, input.error);
      const text = input.text;
      const lines = (text.match(/\n/g) || []).length;
      const words = text.split(/\s+/).filter(Boolean).length;
      if (opts === "l") out(ctx, String(lines));
      else if (opts === "w") out(ctx, String(words));
      else out(ctx, `${padStart(lines, 3)} ${padStart(words, 4)} ${padStart(new TextEncoder().encode(text).length, 5)}`);
    }
    return 0;
  });
  def("sort", (ctx) => {
    const reverse = flags(ctx.args).includes("r");
    for (const input of readInputs(ctx, "sort")) {
      if (input.error) return fail(ctx, input.error, 2);
      const lines = linesOf(input.text).sort((a, b) => a.localeCompare(b, "pt"));
      if (reverse) lines.reverse();
      if (input.text) ctx.out.write(lines.join("\n") + "\n");
    }
    return 0;
  });
  def("echo", (ctx) => {
    let args = ctx.args;
    let newline = true;
    let escapes = false;
    while (args[0] && /^-[neE]+$/.test(args[0])) {
      if (args[0].includes("n")) newline = false;
      if (args[0].includes("e")) escapes = true;
      args = args.slice(1);
    }
    let text = args.join(" ");
    if (escapes) text = text.replace(/\\n/g, "\n").replace(/\\t/g, "\t");
    ctx.out.write(text + (newline ? "\n" : ""));
    return 0;
  });
  def("printf", (ctx) => {
    const [format = "", ...values] = ctx.args;
    let index = 0;
    const text = format.replace(/%[sd%]/g, (spec) => (spec === "%%" ? "%" : values[index++] ?? ""))
      .replace(/\\n/g, "\n").replace(/\\t/g, "\t");
    ctx.out.write(text);
    return 0;
  });
  def("touch", (ctx) => {
    for (const path of ctx.args) {
      const full = resolvePath(ctx.session.cwd, path);
      if (lookup(full)) continue;
      const { dir: folder, name } = parentOf(full);
      if (!folder || folder.type !== "dir") return fail(ctx, `touch: não foi possível tocar '${path}': Arquivo ou diretório inexistente`);
      folder.children[name] = file("");
    }
    return 0;
  });
  def("mkdir", (ctx) => {
    for (const path of ctx.args.filter((a) => !a.startsWith("-"))) {
      const full = resolvePath(ctx.session.cwd, path);
      if (lookup(full)) return fail(ctx, `mkdir: não foi possível criar o diretório “${path}”: Arquivo existe`);
      const { dir: folder, name } = parentOf(full);
      if (!folder || folder.type !== "dir") return fail(ctx, `mkdir: não foi possível criar o diretório “${path}”: Arquivo ou diretório inexistente`);
      folder.children[name] = dir({});
    }
    return 0;
  });
  def("rm rmdir", (ctx) => {
    const recursive = /r/i.test(flags(ctx.args));
    for (const path of ctx.args.filter((a) => !a.startsWith("-"))) {
      const full = resolvePath(ctx.session.cwd, path);
      const node = lookup(full);
      if (!node) return fail(ctx, `rm: não foi possível remover '${path}': Arquivo ou diretório inexistente`);
      if (full === "/" || full === HOME) return fail(ctx, `rm: melhor não. 😉 (mesmo sendo uma demonstração)`);
      if (node.type === "dir" && !recursive && ctx.name === "rm") return fail(ctx, `rm: não foi possível remover '${path}': É um diretório`);
      const { dir: folder, name } = parentOf(full);
      delete folder.children[name];
    }
    return 0;
  });
  def("clear reset", (ctx) => { if (ctx.pane) ctx.pane.clear(); return 0; });
  def("whoami", (ctx) => { out(ctx, USER); return 0; });
  def("hostname", (ctx) => { out(ctx, HOST); return 0; });
  def("id", (ctx) => { out(ctx, "uid=1000(hacker) gid=1000(hacker) grupos=1000(hacker),27(sudo),1001(wireshark)"); return 0; });
  def("uname", (ctx) => {
    const opts = flags(ctx.args);
    if (opts.includes("a")) out(ctx, `Linux ${HOST} 6.12.25-amd64 #1 SMP PREEMPT_DYNAMIC Kali 6.12.25-1kali1 (2025-04-30) x86_64 GNU/Linux`);
    else if (opts.includes("r")) out(ctx, "6.12.25-amd64");
    else out(ctx, "Linux");
    return 0;
  });
  def("date", (ctx) => {
    const now = new Date();
    const fmt = new Intl.DateTimeFormat("pt-BR", { weekday: "short", day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit" });
    const parts = Object.fromEntries(fmt.formatToParts(now).map((p) => [p.type, p.value.replace(".", "")]));
    out(ctx, `${parts.weekday} ${parts.day} ${parts.month} ${parts.year} ${parts.hour}:${parts.minute}:${parts.second} -03`);
    return 0;
  });
  const started = Date.now() - 8220000;
  function uptimeText() {
    const minutes = Math.floor((Date.now() - started) / 60000);
    return `${Math.floor(minutes / 60)}:${String(minutes % 60).padStart(2, "0")}`;
  }
  def("uptime", (ctx) => {
    const time = new Date().toTimeString().slice(0, 8);
    out(ctx, ` ${time} up  ${uptimeText()},  1 user,  load average: 0,42, 0,37, 0,31`);
    return 0;
  });
  def("history", (ctx) => {
    ctx.session.history.forEach((line, index) => out(ctx, `${padStart(index + 1, 5)}  ${line}`));
    return 0;
  });
  def("true", () => 0);
  def("false", () => 1);
  def("exit logout", (ctx) => { if (ctx.pane) ctx.pane.requestExit(); return 0; });
  def("sleep", async (ctx) => {
    const seconds = Math.min(Number(ctx.args[0]) || 0, 30);
    const end = Date.now() + seconds * 1000;
    while (Date.now() < end) { if (ctx.aborted()) return 130; await sleep(Math.min(100, end - Date.now())); }
    return 0;
  });
  def("command which type", (ctx) => {
    const names = ctx.args.filter((a) => !a.startsWith("-"));
    let code = 0;
    for (const name of names) {
      if (COMMANDS[name] && name !== "command") out(ctx, `/usr/bin/${name}`);
      else { code = 1; if (ctx.name !== "command") fail(ctx, `${name} not found`); }
    }
    return code;
  });

  def("ip", (ctx) => {
    const what = ctx.args.filter((a) => !a.startsWith("-"))[0] || "";
    if (what.startsWith("r")) {
      out(ctx, "default via 10.0.2.2 dev eth0 proto dhcp src 10.0.2.15 metric 100");
      out(ctx, "10.0.2.0/24 dev eth0 proto kernel scope link src 10.0.2.15 metric 100");
      out(ctx, "172.17.0.0/16 dev docker0 proto kernel scope link src 172.17.0.1 linkdown");
      return 0;
    }
    if (what.startsWith("a") || what === "") {
      const rows = [["lo", "UNKNOWN", "127.0.0.1/8 ::1/128"], ["eth0", "UP", "10.0.2.15/24 fe80::a00:27ff:fe4e:66a1/64"],
        ["docker0", "DOWN", "172.17.0.1/16"], ["wlan0", "DOWN", ""]];
      for (const [name, stateText, addr] of rows) {
        ctx.out.write(pad(name, 17), "c6");
        ctx.out.write(pad(stateText, 15), stateText === "UP" ? "c2" : stateText === "DOWN" ? "c1" : "");
        out(ctx, addr, "c5");
      }
      return 0;
    }
    return fail(ctx, `Object "${what}" is unknown, try "ip help".`, 255);
  });
  def("ss netstat", (ctx) => {
    out(ctx, "Netid State  Recv-Q Send-Q Local Address:Port  Peer Address:Port Process");
    out(ctx, "udp   UNCONN 0      0          127.0.0.54:53         0.0.0.0:*     uid:991 ino:6012 sk:1");
    out(ctx, "udp   UNCONN 0      0       0.0.0.0%eth0:68          0.0.0.0:*     ino:7731 sk:2");
    out(ctx, "tcp   LISTEN 0      4096        127.0.0.1:631        0.0.0.0:*     ino:6650 sk:3");
    out(ctx, "tcp   LISTEN 0      511         127.0.0.1:8000       0.0.0.0:*     users:((\"python3\",pid=4210,fd=3)) uid:1000");
    out(ctx, "tcp   LISTEN 0      128           0.0.0.0:22         0.0.0.0:*     ino:6871 sk:4");
    return 0;
  });
  def("ps", (ctx) => {
    out(ctx, "USER         PID %CPU %MEM    VSZ   RSS TTY      STAT START   TIME COMMAND");
    const rows = [
      ["hacker", 1873, "3.1", "1.9", 1104332, 152340, "?", "Sl", "/usr/bin/python3 /usr/bin/hacker-terminal"],
      ["hacker", 1412, "1.2", "2.7", 3982120, 221844, "?", "Ssl", "/usr/bin/pipewire"],
      ["root", 902, "0.8", "1.3", 1290044, 105380, "tty7", "Ssl+", "/usr/lib/xorg/Xorg :0"],
      ["hacker", 1655, "0.4", "1.0", 734512, 82220, "?", "Sl", "xfwm4 --replace"],
      ["hacker", 4210, "0.3", "0.3", 31092, 24400, "pts/1", "S", "python3 -m http.server 8000"],
      ["hacker", 1901, "0.1", "0.1", 13872, 8044, "pts/0", "Ss", "/usr/bin/zsh"],
      ["root", 1, "0.0", "0.1", 22540, 13360, "?", "Ss", "/sbin/init splash"],
      ["root", 611, "0.0", "0.1", 50140, 10224, "?", "Ss", "/usr/lib/systemd/systemd-journald"],
      ["root", 745, "0.0", "0.0", 15464, 7380, "?", "Ss", "sshd: /usr/sbin/sshd -D"],
      ["hacker", 4321, "0.0", "0.0", 11204, 4300, "pts/0", "R+", "ps aux --sort=-%cpu"],
    ];
    for (const [user, pid, cpu, mem, vsz, rss, tty, stat, cmd] of rows) {
      out(ctx, `${pad(user, 8)} ${padStart(pid, 7)} ${padStart(cpu, 4)} ${padStart(mem, 4)} ${padStart(vsz, 7)} ${padStart(rss, 6)} ${pad(tty, 8)} ${pad(stat, 4)} 14:12   0:${String(pid % 60).padStart(2, "0")} ${cmd}`);
    }
    return 0;
  });
  def("df", (ctx) => {
    out(ctx, "Sist. Arq.      Tam. Usado Disp. Uso% Montado em");
    out(ctx, "/dev/sda1        79G   31G   44G  42% /");
    return 0;
  });
  def("free", (ctx) => {
    out(ctx, "               total       usada       livre    compart.  buff/cache  disponível");
    out(ctx, "Mem.:          7,7Gi       2,9Gi       1,8Gi       184Mi       3,3Gi       4,8Gi");
    out(ctx, "Swap:          1,0Gi          0B       1,0Gi");
    return 0;
  });
  function addressOf(name) {
    if (/^(localhost|127\.)/.test(name)) return "127.0.0.1";
    if (/^\d+\.\d+\.\d+\.\d+$/.test(name)) return name;
    const h = hash(name);
    return `${45 + (h % 150)}.${(h >> 8) % 256}.${(h >> 16) % 256}.${1 + ((h >> 24) % 254)}`;
  }
  def("ping", async (ctx) => {
    const countIndex = ctx.args.indexOf("-c");
    const limited = countIndex >= 0;
    const count = limited ? Math.min(Number(ctx.args[countIndex + 1]) || 1, 20) : 4;
    const target = ctx.args.filter((a, i) => !a.startsWith("-") && i !== countIndex + 1)[0];
    if (!target) return fail(ctx, "ping: destino de uso necessário", 1);
    const address = addressOf(target);
    const base = address === "127.0.0.1" ? 0.04 : 8 + (hash(target) % 30);
    out(ctx, `PING ${target} (${address}) 56(84) bytes of data.`);
    const times = [];
    for (let seq = 1; seq <= count; seq += 1) {
      if (seq > 1) for (let t = 0; t < 10; t += 1) { if (ctx.aborted()) break; await sleep(100); }
      if (ctx.aborted()) break;
      const time = base + Math.random() * (base / 4 + 0.03);
      times.push(time);
      out(ctx, `64 bytes from ${address}: icmp_seq=${seq} ttl=${address === "127.0.0.1" ? 64 : 54} time=${time.toFixed(time < 1 ? 3 : 1)} ms`);
    }
    out(ctx);
    out(ctx, `--- ${target} ping statistics ---`);
    out(ctx, `${times.length} packets transmitted, ${times.length} received, 0% packet loss, time ${(times.length - 1) * 1001}ms`);
    if (times.length) {
      const avg = times.reduce((a, b) => a + b, 0) / times.length;
      out(ctx, `rtt min/avg/max/mdev = ${Math.min(...times).toFixed(3)}/${avg.toFixed(3)}/${Math.max(...times).toFixed(3)}/${(avg / 9).toFixed(3)} ms`);
    }
    if (!limited && !ctx.aborted()) out(ctx, "(demonstração: sem -c, o ping para depois de 4 pacotes; Ctrl+C para antes)", "c8");
    return ctx.aborted() ? 130 : 0;
  });
  def("nmap", async (ctx) => {
    const target = ctx.args.filter((a) => !a.startsWith("-")).pop();
    if (!target) return fail(ctx, "nmap: informe um alvo. Ex.: nmap -sV scanme.nmap.org");
    const address = addressOf(target);
    out(ctx, `Starting Nmap 7.95 ( https://nmap.org ) at ${new Date().toISOString().slice(0, 16).replace("T", " ")} -03`);
    for (let t = 0; t < 14; t += 1) { if (ctx.aborted()) return 130; await sleep(100); }
    out(ctx, `Nmap scan report for ${target} (${address})`);
    out(ctx, "Host is up (0.012s latency).");
    out(ctx, "Not shown: 996 closed tcp ports (reset)");
    out(ctx, "PORT     STATE SERVICE VERSION", "b");
    const services = [["22/tcp", "ssh", "OpenSSH 9.9p1 Debian 3 (protocol 2.0)"], ["80/tcp", "http", "nginx 1.26.3"],
      ["443/tcp", "ssl/http", "nginx 1.26.3"], ["8000/tcp", "http", "SimpleHTTPServer 0.6 (Python 3.13.3)"]];
    for (const [port, name, version] of services.slice(0, 2 + (hash(target) % 3))) {
      ctx.out.write(pad(port, 9));
      ctx.out.write("open  ", "c2");
      out(ctx, `${pad(name, 8)}${version}`);
    }
    out(ctx, "Service detection performed. Please report any incorrect results at https://nmap.org/submit/ .");
    out(ctx, "Nmap done: 1 IP address (1 host up) scanned in 7.42 seconds");
    out(ctx, "(simulação: nenhum pacote saiu do seu navegador)", "c8");
    return 0;
  });

  const COMMITS = [
    ["dae27df", "Preview themes live in the command palette (0.21.0)", "HEAD -> main, tag: v0.21.0, origin/main"],
    ["869e6da", "Theme dialog buttons; size the result window to its output, in the terminal font"],
    ["a190130", "Site: 0.20.0, the quieter interface, quick actions and real key sounds"],
    ["8e5382f", "Bundle the Mechvibes sound packs, read their v2 format (0.20.0)", "tag: v0.20.0"],
    ["f31f11d", "Site: version 0.19.0"],
    ["a9391a1", "Show a quick action's result in its own window instead of typing it"],
    ["4c733dc", "Show the side panel's actions when it opens from hidden"],
    ["2213603", "Quieter interface, no boot animation, faster startup (0.19.0)", "tag: v0.19.0"],
    ["73cb935", "Release workflow: catch an uncommitted site, allow a dry run on main"],
    ["913cf31", "Refresh every screenshot and publish releases from tags"],
  ];
  def("git", (ctx) => {
    if (!inRepo(ctx.session.cwd)) return fail(ctx, "fatal: não é um repositório git (nem nenhum dos diretórios pais): .git", 128);
    const [sub, ...rest] = ctx.args;
    const decorate = (refs) => {
      if (!refs) return;
      ctx.out.write(" (", "c3");
      refs.split(", ").forEach((ref, index) => {
        if (index) ctx.out.write(", ", "c3");
        if (ref.startsWith("HEAD")) { ctx.out.write("HEAD -> ", "c6 b"); ctx.out.write("main", "c2 b"); }
        else if (ref.startsWith("tag")) ctx.out.write(ref, "c3 b");
        else ctx.out.write(ref, "c1 b");
      });
      ctx.out.write(")", "c3");
    };
    if (sub === "log") {
      const limit = Number((rest.find((a) => /^-\d+$/.test(a)) || "-10").slice(1)) || 10;
      const oneline = rest.includes("--oneline");
      COMMITS.slice(0, limit).forEach(([sha, subject, refs], index) => {
        if (oneline) { ctx.out.write(sha, "c3"); decorate(refs); out(ctx, ` ${subject}`); return; }
        ctx.out.write(`commit ${sha}e1f0c2a9b7d4`, "c3"); decorate(refs); out(ctx);
        out(ctx, "Author: Hiago Lima <hiago@example.com>");
        out(ctx, `Date:   ${index < 2 ? "Fri" : "Thu"} Oct ${17 - Math.floor(index / 3)} ${10 + index}:2${index}:00 2026 -0300`);
        out(ctx);
        out(ctx, `    ${subject}`);
        out(ctx);
      });
      return 0;
    }
    if (sub === "status") {
      out(ctx, "No ramo main");
      out(ctx, "Seu ramo está atualizado com 'origin/main'.");
      out(ctx);
      out(ctx, "nada a submeter, árvore de trabalho limpa");
      return 0;
    }
    if (sub === "branch") { ctx.out.write("* "); out(ctx, "main", "c2"); return 0; }
    if (sub === "remote") { out(ctx, rest.includes("-v") ? "origin\thttps://github.com/Hiagolim11/hacker-terminal.git (fetch)\norigin\thttps://github.com/Hiagolim11/hacker-terminal.git (push)" : "origin"); return 0; }
    if (sub === "diff") return 0;
    if (!sub) { out(ctx, "uso: git [--version] [--help] <comando> [<args>]"); out(ctx, "nesta demonstração: git status, git log [--oneline] [-N], git branch, git remote -v", "c8"); return 1; }
    return fail(ctx, `git: '${sub}' não é um comando do git (aqui só há status, log, branch, remote e diff).`);
  });

  def("neofetch fastfetch", (ctx) => {
    const theme = currentTheme();
    const logo = [
      "  ┌──────────────────┐ ",
      "  │ ▶_               │ ",
      "  │                  │ ",
      "  │   hacker         │ ",
      "  │      terminal    │ ",
      "  │                  │ ",
      "  └──────────────────┘ ",
      "        ▀▀▀▀▀▀▀▀       ",
      "                       ",
      "                       ",
      "                       ",
      "                       ",
      "                       ",
    ];
    const info = [
      [`${USER}@${HOST}`, "", "title"], ["-------", "", "rule"],
      ["SO", "Kali GNU/Linux Rolling x86_64"], ["Kernel", "6.12.25-amd64"], ["Uptime", uptimeText().replace(":", " h ") + " min"],
      ["Shell", "zsh 5.9"], ["Terminal", `hacker-terminal ${VERSION}`], ["Tema", `${theme.name} (${theme.id})`],
      ["Fonte", `${state.font} ${state.fontSize}`], ["Perfil", PROFILES.get(state.profile)?.name || "personalizado"],
      ["Som", state.sound ? PACKS.get(state.pack)?.name || "ligado" : "desligado"], ["CPU", "Intel i7-1165G7 (8) @ 4.70 GHz"], ["Memória", "2,9 GiB / 7,7 GiB"],
    ];
    logo.forEach((art, index) => {
      ctx.out.write(art, "c2 b");
      const row = info[index];
      if (!row) { out(ctx); return; }
      if (row[2] === "title") { ctx.out.write(USER, "c2 b"); ctx.out.write("@"); out(ctx, HOST, "c2 b"); }
      else if (row[2] === "rule") out(ctx, "-".repeat(USER.length + HOST.length + 1));
      else { ctx.out.write(row[0], "c2 b"); out(ctx, `: ${row[1]}`); }
    });
    out(ctx);
    const blocks = (from) => { ctx.out.write(" ".repeat(23)); for (let i = from; i < from + 8; i += 1) ctx.out.write("   ", "", `background:var(--c${i})`); out(ctx); };
    blocks(0); blocks(8);
    return 0;
  });

  def("cores colors", (ctx) => {
    const theme = currentTheme();
    const names = ["preto", "vermelho", "verde", "amarelo", "azul", "magenta", "ciano", "branco"];
    out(ctx, `${theme.name}: as 16 cores ANSI (normais e claras)`, "b");
    names.forEach((name, i) => {
      ctx.out.write(` ${padStart(i, 2)} `);
      ctx.out.write("    ", "", `background:var(--c${i})`);
      ctx.out.write(` ${pad(name, 9)}`, `c${i}`);
      ctx.out.write(pad(theme.ansi[i], 10), "c8");
      ctx.out.write(`${padStart(i + 8, 2)} `);
      ctx.out.write("    ", "", `background:var(--c${i + 8})`);
      ctx.out.write(` ${pad(name + " claro", 15)}`, `c${i + 8}`);
      out(ctx, theme.ansi[i + 8], "c8");
    });
    out(ctx, `fundo ${theme.term.background} · texto ${theme.term.foreground} · cursor ${theme.term.cursor} · destaque ${theme.ui.accent}`, "c8");
    return 0;
  });

  /* settings commands: the same knobs as the Preferences dialog */
  def("tema theme", (ctx) => {
    const query = ctx.args.join(" ");
    if (!query || query === "lista" || query === "--list") {
      for (const theme of THEMES.values()) {
        const active = theme.id === state.theme;
        ctx.out.write(active ? "● " : "  ", "c2");
        ctx.out.write(pad(theme.id, 22), active ? "c2 b" : "");
        out(ctx, theme.name, "c8");
      }
      out(ctx, "use: tema <nome>   (ex.: tema neon-noir, tema fósforo âmbar, tema aleatório)", "c8");
      return 0;
    }
    let theme = /^(aleat|random)/.test(normalize(query)) ? [...THEMES.values()][Math.floor(Math.random() * THEMES.size)] : findTheme(query);
    if (!theme) return fail(ctx, `tema: não encontrei “${query}”. Digite tema para ver a lista.`);
    app.setTheme(theme.id);
    ctx.out.write("Tema aplicado: ", "c8");
    out(ctx, theme.name, "c2 b");
    if (theme.font && WEB_FONT_FOR[theme.font] && state.font !== WEB_FONT_FOR[theme.font]) {
      out(ctx, `Dica: este tema sugere a fonte ${theme.font}. Experimente: fonte ${WEB_FONT_FOR[theme.font]}`, "c8");
    }
    if (!state.effects && (theme.fx.glow || theme.fx.curvature || theme.fx.rain)) out(ctx, "Os efeitos estão desligados: efeitos on", "c8");
    return 0;
  });
  def("perfil profile", (ctx) => {
    const query = ctx.args.join(" ");
    if (!query) {
      for (const profile of PROFILES.values()) {
        const active = profile.id === state.profile;
        ctx.out.write(active ? "● " : "  ", "c2");
        ctx.out.write(pad(profile.id, 12), active ? "c2 b" : "");
        ctx.out.write(pad(profile.name, 18));
        out(ctx, profile.description, "c8");
      }
      return 0;
    }
    const profile = findProfile(query);
    if (!profile) return fail(ctx, `perfil: não encontrei “${query}”.`);
    app.applyProfile(profile.id);
    ctx.out.write("Perfil aplicado: ", "c8");
    out(ctx, `${profile.name} — ${profile.description}`, "c2");
    return 0;
  });
  const onOff = (arg, current) => (arg == null || arg === "" ? !current : !/^(off|0|false|nao|desligar|desliga)$/.test(normalize(arg)));
  def("efeitos effects", (ctx) => {
    app.set({ effects: onOff(ctx.args[0], state.effects) });
    out(ctx, `Efeitos visuais ${state.effects ? "ligados" : "desligados"}.`, "c8");
    return 0;
  });
  def("som sound", (ctx) => {
    const arg = ctx.args.join(" ");
    const pack = arg && [...PACKS.values()].find((p) => p.id.startsWith(normalize(arg)) || normalize(p.name).startsWith(normalize(arg)));
    if (normalize(arg) === "lista") { PACKS.forEach((p) => out(ctx, `${p.id === state.pack ? "● " : "  "}${pad(p.id, 16)} ${p.name}`)); return 0; }
    if (pack) app.set({ sound: true, pack: pack.id });
    else app.set({ sound: onOff(arg || null, state.sound) });
    out(ctx, state.sound ? `Som do teclado ligado: ${PACKS.get(state.pack).name}. Digite algo para ouvir.` : "Som do teclado desligado.", "c8");
    if (!arg) out(ctx, `pacotes: ${[...PACKS.keys()].join(", ")}`, "c8");
    return 0;
  });
  def("fonte font", (ctx) => {
    const arg = ctx.args.join(" ");
    if (!arg) {
      out(ctx, `${state.font} ${state.fontSize}`);
      out(ctx, `famílias: ${FONTS.map((f) => f.name).join(", ")} · tamanhos 8–24 · fonte + / fonte -`, "c8");
      return 0;
    }
    if (arg === "+" || arg === "-") app.zoom(arg === "+" ? 1 : -1);
    else if (/^\d+$/.test(arg)) app.set({ fontSize: Math.max(8, Math.min(24, Number(arg))) });
    else {
      const family = FONTS.find((f) => normalize(f.name).startsWith(normalize(arg)));
      if (!family) return fail(ctx, `fonte: “${arg}” não está disponível aqui (${FONTS.map((f) => f.name).join(", ")}).`);
      app.set({ font: family.name });
    }
    out(ctx, `Fonte: ${state.font} ${state.fontSize}`, "c8");
    return 0;
  });
  def("cursor", (ctx) => {
    const map = { bloco: "block", block: "block", barra: "ibeam", ibeam: "ibeam", sublinhado: "underline", underline: "underline" };
    const shape = map[normalize(ctx.args[0] || "")];
    if (!shape) return fail(ctx, "cursor: use bloco, barra ou sublinhado");
    app.set({ cursor: shape });
    return 0;
  });
  def("painel panel", () => { app.set({ panel: !state.panel }); return 0; });
  def("matrix cmatrix", async (ctx) => {
    if (!ctx.pane) return 0;
    app.rain.boost = true;
    app.updateEffects();
    ctx.pane.waitingKey = true;
    while (ctx.pane.waitingKey && !ctx.aborted()) await sleep(80);
    ctx.pane.waitingKey = false;
    app.rain.boost = false;
    app.updateEffects();
    return 0;
  });

  def("hacker-terminal ht", (ctx) => {
    const args = ctx.args;
    if (!args.length) { app.newTab(); return 0; }
    const value = (name) => { const i = args.indexOf(name); return i >= 0 ? args[i + 1] : undefined; };
    if (args.includes("--version")) { out(ctx, `hacker-terminal ${VERSION}`); return 0; }
    if (args.includes("--help") || args.includes("-h")) {
      out(ctx, "uso: hacker-terminal [-h] [--version] [--diagnose] [--list-shortcuts] [--theme ID] [--list-themes]");
      out(ctx, "                     [--profile ID] [--list-profiles] [--no-effects] [--no-sound] [--no-panel] [-e ...]");
      out(ctx);
      out(ctx, "Terminal nativo para Linux com temas, perfis, ações rápidas e som de teclado mecânico.");
      return 0;
    }
    if (args.includes("--list-themes")) { THEMES.forEach((t) => out(ctx, `${pad(t.id, 22)}${t.name}`)); return 0; }
    if (args.includes("--list-profiles")) { PROFILES.forEach((p) => out(ctx, `${pad(p.id, 12)}${pad(p.name, 18)}${p.description}`)); return 0; }
    if (args.includes("--list-shortcuts")) { SHORTCUTS.forEach(([label, keys]) => out(ctx, `${pad(keys, 16)}${label}`)); return 0; }
    if (args.includes("--diagnose")) {
      const rows = [["Hacker Terminal", VERSION], ["GTK", "3.24.52"], ["VTE", "0.84.1"], ["Fonte selecionada", state.font],
        ["Powerline", "OK"], ["Nerd Font", "OK"], ["Shell", "/usr/bin/zsh"], ["Integração com o shell", "OK (VTE 0.78+)"],
        ["Tema", `${currentTheme().name} (${state.theme})`], ["Temas internos", String(THEMES.size)],
        ["Som", state.sound ? `pack:${state.pack}` : "desligado"], ["GStreamer", "1.26.2"], ["Config", "~/.config/hacker-terminal/config.ini"]];
      rows.forEach(([k, v], i) => out(ctx, i ? `${k}: ${v}` : `${k} ${v}`));
      return 0;
    }
    const patch = {};
    const theme = value("--theme");
    if (theme) { const t = findTheme(theme); if (!t) return fail(ctx, `hacker-terminal: tema desconhecido: ${theme}`, 2); patch.theme = t.id; }
    const profile = value("--profile");
    if (profile) { const p = findProfile(profile); if (!p) return fail(ctx, `hacker-terminal: perfil desconhecido: ${profile}`, 2); app.applyProfile(p.id); }
    if (args.includes("--no-effects")) patch.effects = false;
    if (args.includes("--no-sound")) patch.sound = false;
    if (args.includes("--no-panel")) patch.panel = false;
    app.set(patch);
    app.newTab();
    return 0;
  });

  def("ht-open xdg-open", (ctx) => {
    const inline = ctx.args.includes("--inline");
    const path = ctx.args.find((a) => !a.startsWith("-"));
    if (!path) return fail(ctx, "uso: ht-open [--inline] ARQUIVO", 2);
    const node = lookup(resolvePath(ctx.session.cwd, path));
    if (!node) return fail(ctx, `ht-open: ${path}: Arquivo ou diretório inexistente`);
    if (!node.image) return fail(ctx, `ht-open: ${path}: esta demonstração só abre as imagens de docs/screenshots`);
    const name = path.split("/").pop();
    if (inline && ctx.pane) { ctx.pane.writeImage(node.image, name); return 0; }
    app.openViewer(node.image, name);
    out(ctx, `Abrindo ${name} numa aba do visualizador…`, "c8");
    return 0;
  });

  const NEEDS_TERMINAL = "vim vi nvim nano emacs htop top btop tmux screen ssh sudo su man python python3 watch msfconsole";
  def(NEEDS_TERMINAL, (ctx) => {
    if (ctx.name === "sudo" || ctx.name === "su") return fail(ctx, `${ctx.name}: nesta demonstração você não tem poderes de root. 😉 No app, o sudo pede a senha normalmente.`);
    return fail(ctx, `${ctx.name}: no app de verdade o ${ctx.name} abre aqui mesmo, em tela cheia; esta demonstração só simula o shell.`);
  });

  const COMMAND_NAMES = Object.keys(COMMANDS).sort();

  /* ---------- running a command line ---------- */

  async function runLine(session, line, sinks) {
    let list;
    try { list = parse(lex(line)); } catch (error) {
      sinks.err.write(`zsh: ${error.message}\n`, "c1");
      return 1;
    }
    let code = session.lastCode;
    for (const { op, pipeline } of list) {
      if (op === "&&" && code !== 0) continue;
      if (op === "||" && code === 0) continue;
      code = await runPipeline(session, pipeline, sinks);
      session.lastCode = code;
      if (session.aborted) return 130;
    }
    return code;
  }

  async function runPipeline(session, pipeline, sinks) {
    let stdin = null;
    let code = 0;
    for (let index = 0; index < pipeline.length; index += 1) {
      const command = pipeline[index];
      const last = index === pipeline.length - 1;
      const words = command.words.flatMap((word) => expandWord(word, session));
      let stdout = last ? sinks.out : new Collector();
      let stderr = sinks.err;
      const files = [];
      for (const redirect of command.redirects) {
        if (redirect.dup) { if (redirect.fd === 2) stderr = stdout; continue; }
        const target = expandWord(redirect.target, session)[0];
        if (redirect.fd === 0) {
          const node = lookup(resolvePath(session.cwd, target));
          if (!node || node.type !== "file") { sinks.err.write(`zsh: arquivo ou diretório inexistente: ${target}\n`, "c1"); return 1; }
          stdin = readFile(node);
          continue;
        }
        const sink = target === "/dev/null" ? NULL_SINK : new FileSink(resolvePath(session.cwd, target), redirect.append);
        if (sink !== NULL_SINK) files.push(sink);
        if (redirect.fd === 2) stderr = sink; else stdout = sink;
      }
      const [name, ...args] = words;
      if (name === undefined) { files.forEach((f) => f.close()); continue; }
      const assignment = /^([A-Za-z_]\w*)=(.*)$/.exec(name);
      if (assignment && !args.length) { session.env[assignment[1]] = assignment[2]; code = 0; continue; }
      const handler = Object.hasOwn(COMMANDS, name) ? COMMANDS[name] : null;
      const tty = stdout === sinks.out && sinks.tty;
      if (!handler) {
        const node = name.includes("/") ? lookup(resolvePath(session.cwd, name)) : null;
        if (node && node.exec) { stdout.write(`${name}: executado (demonstração)\n`); code = 0; }
        else if (node && node.type === "dir") { stderr.write(`zsh: permissão negada: ${name}\n`, "c1"); code = 126; }
        else { stderr.write(`zsh: comando não encontrado: ${name}\n`, "c1"); code = 127; }
      } else {
        const ctx = {
          name, args, stdin, session, tty, out: stdout, err: stderr,
          pane: session.pane || null,
          aborted: () => session.aborted,
        };
        code = await handler(ctx);
      }
      for (const sink of files) if (!sink.close()) { sinks.err.write(`zsh: não foi possível escrever em ${sink.path}\n`, "c1"); code = 1; }
      stdin = stdout instanceof Collector && !(stdout instanceof FileSink) ? stdout.text : "";
      if (session.aborted) return 130;
    }
    return code;
  }

  /* ---------- keyboard sound (the Mechvibes recordings the app ships) ---------- */

  const sound = {
    context: null,
    buffers: new Map(),
    loading: new Map(),
    gain: null,
    ensure() {
      if (!this.context) {
        const Context = window.AudioContext || window.webkitAudioContext;
        if (!Context) return false;
        this.context = new Context({ latencyHint: "interactive" });
        this.gain = this.context.createGain();
        this.gain.connect(this.context.destination);
      }
      if (this.context.state === "suspended") this.context.resume();
      this.gain.gain.value = (state.volume / 100) ** 1.6;
      return true;
    },
    load(pack) {
      if (!this.ensure()) return Promise.resolve();
      if (this.loading.has(pack.id)) return this.loading.get(pack.id);
      const files = new Set([...pack.press, pack.release, ...Object.values(pack.keys).flatMap((k) => [k.press, k.release])].filter(Boolean));
      const promise = Promise.all([...files].map((name) => fetch(pack.base + name)
        .then((r) => r.arrayBuffer())
        .then((data) => new Promise((resolve, reject) => this.context.decodeAudioData(data, resolve, reject)))
        .then((buffer) => this.buffers.set(pack.base + name, buffer))
        .catch(() => {})));
      this.loading.set(pack.id, promise);
      return promise;
    },
    play(kind, key) {
      if (!state.sound || (kind === "release" && !state.keyRelease)) return;
      const pack = PACKS.get(state.pack);
      if (!pack || !this.ensure()) return;
      this.load(pack);
      const special = pack.keys[key === " " ? "Space" : key];
      let name = special && special[kind];
      if (!name) name = kind === "press" ? pack.press[Math.floor(Math.random() * pack.press.length)] : pack.release;
      const buffer = name && this.buffers.get(pack.base + name);
      if (!buffer) return;
      const node = this.context.createBufferSource();
      node.buffer = buffer;
      node.playbackRate.value = 0.97 + Math.random() * 0.06;  // each key a little different
      node.connect(this.gain);
      node.start();
    },
  };
  const soundKey = (event) => event.key.length === 1 || ["Enter", "Backspace", "Tab", "Delete"].includes(event.key);

  /* ---------- panes, tabs and the window ---------- */

  let paneCounter = 0;

  class Pane {
    constructor(tab, cwd) {
      this.tab = tab;
      this.id = ++paneCounter;
      this.cwd = cwd || `${HOME}/hacker-terminal`;
      this.oldCwd = null;
      this.env = { HOME, USER, SHELL: "/usr/bin/zsh", TERM: "xterm-256color", LANG: "pt_BR.UTF-8", HACKER_TERMINAL_VERSION: VERSION };
      this.history = app.sharedHistory;
      this.historyIndex = null;
      this.buffer = "";
      this.caret = 0;
      this.busy = false;
      this.aborted = false;
      this.lastCode = 0;
      this.failedCode = 0;
      this.marks = [];
      this.markIndex = -1;
      this.lastOutput = "";
      this.waitingKey = false;
      this.screen = el("div", { class: "ht-screen", "aria-label": "Saída do terminal" });
      this.inputLine = el("div", { class: "ht-line ht-prompt" });
      this.screen.append(this.inputLine);
      this.node = el("div", { class: "ht-pane" }, this.screen);
      this.node.addEventListener("mousedown", () => { if (app.focusedPane() !== this) app.focusPane(this); });
      this.node.addEventListener("click", () => {
        if (String(getSelection()).length) return;
        app.focusPane(this, true);
      });
      this.current = null;
      this.renderInput();
    }

    get session() { return this; }
    get pane() { return this; }
    columns() { return Math.max(20, Math.floor((this.screen.clientWidth - 24) / app.charWidth())); }

    newLine() {
      const line = el("div", { class: "ht-line" });
      this.screen.insertBefore(line, this.inputLine);
      this.current = line;
      const extra = this.screen.childElementCount - 2500;
      for (let i = 0; i < extra; i += 1) this.screen.firstElementChild.remove();
      return line;
    }
    write(text, cls, style) {
      const pieces = String(text).split("\n");
      pieces.forEach((piece, index) => {
        if (index > 0) {  // a newline ends the open line, or makes an empty one
          if (!this.current) this.newLine();
          this.current = null;
        }
        if (!piece) return;
        if (!this.current) this.newLine();
        if (cls || style) this.current.append(el("span", { class: cls || null, style: style || null, text: piece }));
        else this.current.append(piece);
      });
      this.scrollToEnd();
    }
    writeImage(url, name) {
      const line = this.newLine();
      line.append(el("img", { src: url, alt: name, loading: "lazy", onload: () => this.scrollToEnd() }));
      this.current = null;
    }
    scrollToEnd() { this.screen.scrollTop = this.screen.scrollHeight; }
    clear() {
      [...this.screen.children].forEach((child) => { if (child !== this.inputLine) child.remove(); });
      this.current = null;
      this.marks = [];
      this.markIndex = -1;
    }

    promptParts() {
      const parts = [["➜ ", "c2 b"], [shortPath(this.cwd), "c6 b"]];
      if (inRepo(this.cwd)) parts.push([" (", "c4 b"], ["main", "c1 b"], [")", "c4 b"]);
      parts.push([" $ ", ""]);
      return parts;
    }
    suggestion() {
      if (!this.buffer || this.caret !== this.buffer.length) return "";
      for (let i = this.history.length - 1; i >= 0; i -= 1) {
        if (this.history[i].startsWith(this.buffer) && this.history[i] !== this.buffer) return this.history[i].slice(this.buffer.length);
      }
      return "";
    }
    renderInput() {
      const line = this.inputLine;
      line.replaceChildren();
      line.hidden = this.busy;
      if (this.busy) return;
      for (const [text, cls] of this.promptParts()) line.append(cls ? el("span", { class: cls, text }) : text);
      const buffer = this.buffer;
      // zsh-syntax-highlighting: the command word is green when it exists, red when not
      const first = /^\s*(\S+)/.exec(buffer);
      const known = first && (Object.hasOwn(COMMANDS, first[1]) || /^[A-Za-z_]\w*=/.test(first[1]) || lookup(resolvePath(this.cwd, first[1]))?.exec);
      const wordEnd = first ? first.index + first[0].length : 0;
      const wordStart = first ? wordEnd - first[1].length : 0;
      const segment = (from, to) => {
        const frag = [];
        if (from < wordEnd && to > wordStart) {
          const a = Math.max(from, wordStart);
          const b = Math.min(to, wordEnd);
          if (a > from) frag.push(buffer.slice(from, a));
          frag.push(el("span", { class: known ? "c2" : "c1", text: buffer.slice(a, b) }));
          if (to > b) frag.push(buffer.slice(b, to));
        } else frag.push(buffer.slice(from, to));
        return frag;
      };
      line.append(...segment(0, this.caret));
      const under = buffer[this.caret] || " ";
      const blink = state.blink && !REDUCED_MOTION ? " blink" : "";
      line.append(el("span", { class: `ht-cursor ${state.cursor}${blink}`, text: under }));
      line.append(...segment(this.caret + 1, buffer.length));
      const hint = this.suggestion();
      if (hint) line.append(el("span", { class: "c8", text: hint }));
      this.scrollToEnd();
    }

    setBuffer(text, caret = text.length) {
      this.buffer = text;
      this.caret = caret;
      this.renderInput();
    }

    async submit(line = this.buffer) {
      if (this.busy) return;
      const commandLine = el("div", { class: "ht-line" });
      for (const [text, cls] of this.promptParts()) commandLine.append(cls ? el("span", { class: cls, text }) : text);
      commandLine.append(line);
      this.screen.insertBefore(commandLine, this.inputLine);
      this.current = null;
      this.historyIndex = null;
      this.buffer = "";
      this.caret = 0;
      if (!line.trim()) { this.renderInput(); return; }
      if (!line.startsWith(" ") && this.history[this.history.length - 1] !== line) this.history.push(line);
      this.busy = true;
      this.aborted = false;
      this.renderInput();
      app.refreshChrome();
      const startedAt = performance.now();
      const capture = new Collector();
      const pane = this;
      const sink = {
        write(text, cls, style) { capture.write(text); pane.write(text, cls, style); },
      };
      const errSink = { write(text, cls) { pane.write(text, cls || "c1"); } };
      const code = await runLine(this, line, { out: sink, err: errSink, tty: true });
      if (this.current) this.current = null;
      if (this.aborted) this.write("^C\n", "c8");
      this.lastCode = code;
      this.failedCode = code;
      this.lastOutput = capture.text;
      if (state.marks && commandLine.isConnected) {
        commandLine.classList.add("mark", code === 0 ? "ok" : "fail");
        this.marks.push(commandLine);
      }
      app.recordHistory({ command: line.trim(), code, duration: performance.now() - startedAt, cwd: shortPath(this.cwd), when: new Date(), place: this.tab.title() });
      this.busy = false;
      this.aborted = false;
      this.markIndex = -1;
      this.renderInput();
      app.refreshChrome();
      if (this.exitRequested) { this.exitRequested = false; app.closePane(this); }
    }
    requestExit() { this.exitRequested = true; }

    complete() {
      const before = this.buffer.slice(0, this.caret);
      const match = /(\S*)$/.exec(before);
      const word = match[1];
      const isCommand = !before.slice(0, before.length - word.length).trim();
      let candidates;
      let base = "";
      if (isCommand && !word.includes("/")) {
        candidates = COMMAND_NAMES.filter((name) => name.startsWith(word));
      } else {
        const slash = word.lastIndexOf("/");
        base = slash >= 0 ? word.slice(0, slash + 1) : "";
        const folder = lookup(resolvePath(this.cwd, base || "."));
        const prefix = word.slice(slash + 1);
        candidates = folder && folder.type === "dir"
          ? Object.entries(folder.children).filter(([name]) => name.startsWith(prefix) && (prefix.startsWith(".") || !name.startsWith(".")))
            .map(([name, node]) => name + (node.type === "dir" ? "/" : "")).sort()
          : [];
      }
      if (!candidates.length) return;
      let common = candidates[0];
      for (const candidate of candidates) while (!candidate.startsWith(common)) common = common.slice(0, -1);
      const typed = word.slice(base.length);
      if (common.length > typed.length || candidates.length === 1) {
        const completion = base + common + (candidates.length === 1 && !common.endsWith("/") ? " " : "");
        const start = before.length - word.length;
        this.setBuffer(this.buffer.slice(0, start) + completion + this.buffer.slice(this.caret), start + completion.length);
        return;
      }
      this.current = null;
      const width = Math.max(...candidates.map((c) => c.length)) + 2;
      const perRow = Math.max(1, Math.floor(this.columns() / width));
      for (let i = 0; i < candidates.length; i += perRow) this.write(candidates.slice(i, i + perRow).map((c) => pad(c, width)).join("").trimEnd() + "\n");
      this.renderInput();
    }

    historyStep(direction) {
      if (!this.history.length) return;
      if (this.historyIndex === null) { this.draft = this.buffer; this.historyIndex = this.history.length; }
      this.historyIndex = Math.max(0, Math.min(this.history.length, this.historyIndex + direction));
      this.setBuffer(this.historyIndex === this.history.length ? this.draft : this.history[this.historyIndex]);
    }

    jumpMark(direction) {
      const marks = this.marks.filter((m) => m.isConnected);
      if (!marks.length) return;
      if (this.markIndex < 0) this.markIndex = direction < 0 ? marks.length : -1;
      this.markIndex = Math.max(0, Math.min(marks.length - 1, this.markIndex + direction));
      const mark = marks[this.markIndex];
      this.screen.scrollTop = mark.offsetTop - this.screen.clientHeight / 2;
      mark.classList.remove("flash");
      void mark.offsetWidth;
      mark.classList.add("flash");
    }
  }

  class Tab {
    constructor(kind = "term", extra = {}) {
      this.kind = kind;
      this.panes = [];
      this.focused = 0;
      this.direction = "h";
      this.broadcast = false;
      Object.assign(this, extra);
    }
    title() {
      if (this.kind === "viewer") return this.name;
      const pane = this.panes[this.focused];
      const path = shortPath(pane.cwd);
      return path === "~" ? "~" : path.split("/").pop();
    }
  }

  /* ---------- effects: digital rain, noise, CRT look ---------- */

  const rain = {
    canvas: null,
    context: null,
    drops: [],
    boost: false,
    running: false,
    visible: true,
    last: 0,
    resize() {
      if (!this.canvas) return;
      const box = this.canvas.parentElement.getBoundingClientRect();
      const ratio = Math.min(window.devicePixelRatio || 1, 2);
      this.canvas.width = Math.max(1, Math.round(box.width * ratio));
      this.canvas.height = Math.max(1, Math.round(box.height * ratio));
      this.context.setTransform(ratio, 0, 0, ratio, 0, 0);
      const columns = Math.ceil(box.width / 16);
      this.drops = Array.from({ length: columns }, (_, i) => this.drops[i] || { y: Math.random() * -60, speed: 0.3 + Math.random() * 0.5, chars: [] });
      this.height = box.height;
    },
    glyph() { return "アカサタナハマヤラワ0123456789ｦｱｳｴｵｶｷｸｹｺｻｼｽｾｿﾀﾁﾂﾃﾄ:.=*+<>"[Math.floor(Math.random() * 46)]; },
    frame(time) {
      if (!this.running) return;
      requestAnimationFrame((t) => this.frame(t));
      if (time - this.last < 55) return;
      this.last = time;
      this.draw(true);
    },
    draw(step) {
      const ctx = this.context;
      if (!ctx) return;
      const [r, g, b] = rgb(this.color || "#39ff88");
      const strength = this.boost ? 0.95 : 0.1;  // like the app: a quiet rain behind the text
      const trail = this.boost ? 22 : 12;
      ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
      ctx.font = "15px 'JetBrains Mono', monospace";
      ctx.textBaseline = "top";
      this.drops.forEach((drop, column) => {
        if (step) {
          drop.y += drop.speed;
          if (Math.random() < 0.3) drop.chars.unshift(this.glyph());
          drop.chars.length = Math.min(drop.chars.length, trail);
          if ((drop.y - trail) * 17 > this.height && Math.random() > 0.96) { drop.y = Math.random() * (this.boost ? -10 : -60); drop.chars = []; }
        }
        for (let i = 0; i < drop.chars.length; i += 1) {
          const y = (Math.floor(drop.y) - i) * 17;
          if (y < -17 || y > this.height) continue;
          const alpha = i === 0 ? strength * 1.4 : strength * (1 - i / trail);
          ctx.fillStyle = i === 0 && this.boost ? `rgba(230,255,240,${Math.min(1, alpha)})` : `rgba(${r},${g},${b},${Math.max(0, alpha)})`;
          ctx.fillText(drop.chars[i], column * 16 + 2, y);
        }
      });
    },
    update(enabled, color) {
      this.color = color;
      const want = enabled && this.visible && !document.hidden;
      if (!enabled && this.context) this.context.clearRect(0, 0, this.canvas.width, this.canvas.height);
      if (want && REDUCED_MOTION) { this.running = false; this.resize(); for (let i = 0; i < 30; i += 1) this.draw(true); return; }
      if (want && !this.running) { this.running = true; this.resize(); requestAnimationFrame((t) => this.frame(t)); }
      if (!want) this.running = false;
    },
  };

  function noiseTile() {
    const canvas = document.createElement("canvas");
    canvas.width = canvas.height = 128;
    const ctx = canvas.getContext("2d");
    const data = ctx.createImageData(128, 128);
    for (let i = 0; i < data.data.length; i += 4) {
      const v = Math.random() * 255;
      data.data[i] = data.data[i + 1] = data.data[i + 2] = v;
      data.data[i + 3] = 255;
    }
    ctx.putImageData(data, 0, 0);
    return canvas.toDataURL();
  }

  /* ---------- the application ---------- */

  const app = {
    tabs: [],
    active: 0,
    sharedHistory: [],
    commandLog: [],
    rain,
    overlay: null,

    build() {
      const icon = (path) => {
        const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
        svg.setAttribute("viewBox", "0 0 24 24");
        svg.setAttribute("fill", "none");
        svg.setAttribute("stroke", "currentColor");
        svg.setAttribute("stroke-width", "2");
        svg.setAttribute("stroke-linecap", "round");
        svg.setAttribute("stroke-linejoin", "round");
        svg.setAttribute("aria-hidden", "true");
        svg.innerHTML = path;
        return svg;
      };
      const button = (label, path, onclick, extra = {}) => el("button", { class: "ht-btn", type: "button", title: label, "aria-label": label, onclick, ...extra }, icon(path));
      this.panelButton = button("Ações rápidas (Ctrl+Shift+B)", '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M15 4v16"/>', () => this.set({ panel: !state.panel }), { "aria-pressed": "false" });
      this.title = el("div", { class: "ht-title" });
      this.tabBar = el("div", { class: "ht-tabs", role: "tablist", hidden: true });
      this.panesNode = el("div", { class: "ht-panes" });
      this.fx = el("div", { class: "ht-fx", "aria-hidden": "true" },
        el("div", { class: "ht-light" }),
        rain.canvas = el("canvas", { class: "ht-rain" }),
        el("div", { class: "ht-scan" }),
        this.noise = el("div", { class: "ht-noise" }),
        el("div", { class: "ht-vignette" }),
        el("div", { class: "ht-tube" }));
      rain.context = rain.canvas.getContext("2d");
      this.work = el("div", { class: "ht-work" }, this.panesNode, this.fx);
      this.panel = el("aside", { class: "ht-panel", "aria-label": "Ações rápidas", hidden: true });
      this.statusLeft = el("span");
      this.statusRight = el("span", { class: "right" });
      this.toast = el("div", { class: "ht-toast", role: "status" });
      this.input = el("input", { class: "ht-input", type: "text", autocomplete: "off", autocapitalize: "off", autocorrect: "off", spellcheck: "false",
        "aria-label": "Linha de comando do terminal de demonstração", enterkeyhint: "go" });
      this.root = el("div", { class: "ht", role: "application", "aria-label": "Demonstração interativa do Hacker Terminal", "aria-roledescription": "terminal" },
        el("div", { class: "ht-header" },
          el("div", { class: "ht-group" }, button("Nova aba (Ctrl+Shift+T)", '<rect x="3" y="5" width="18" height="15" rx="2"/><path d="M12 9v7M8.5 12.5h7"/>', () => this.newTab())),
          this.title,
          el("div", { class: "ht-group" },
            button("Paleta de comandos (Ctrl+Shift+P)", '<circle cx="11" cy="11" r="6"/><path d="M20 20l-4.5-4.5"/>', () => this.openPalette()),
            button("Dividir lado a lado (Ctrl+Shift+D)", '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M12 4v16"/>', () => this.split("h")),
            this.panelButton,
            button("Preferências (Ctrl+,)", '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>', () => this.openPreferences()),
            el("span", { class: "ht-dots", "aria-hidden": "true" }, el("i"), el("i"), el("i")))),
        this.tabBar,
        el("div", { class: "ht-body" }, this.work, this.panel),
        el("div", { class: "ht-status" }, this.statusLeft, this.statusRight),
        this.toast,
        this.input);
      host.replaceChildren(this.root);
      this.noise.style.backgroundImage = `url(${noiseTile()})`;
      this.buildPanel();
      this.bindKeys();
      this.root.addEventListener("focusin", () => this.root.classList.add("has-focus"));
      this.root.addEventListener("focusout", (event) => { if (!this.root.contains(event.relatedTarget)) this.root.classList.remove("has-focus"); });
      new ResizeObserver(() => rain.resize()).observe(this.work);
      if ("IntersectionObserver" in window) {
        new IntersectionObserver(([entry]) => { rain.visible = entry.isIntersecting; this.updateEffects(); }).observe(this.root);
      }
      document.addEventListener("visibilitychange", () => this.updateEffects());
      document.addEventListener("fullscreenchange", () => setTimeout(() => rain.resize(), 50));
    },

    buildPanel() {
      this.panel.replaceChildren(el("h4", { text: "Ações rápidas" }),
        ...DATA.actions.map((action) => el("button", { type: "button", title: action.command, onclick: () => this.runAction(action) },
          action.label + (action.fields.length ? " …" : ""))),
        el("button", { type: "button", class: "edit", onclick: () => this.showToast("No app, “Editar ações…” abre o editor; aqui as ações são as padrão.") }, "Editar ações…"));
    },

    /* tabs and panes */
    currentTab() { return this.tabs[this.active]; },
    focusedPane() { const tab = this.currentTab(); return tab && tab.kind === "term" ? tab.panes[tab.focused] : null; },
    newTab(cwd, giveFocus = true) {
      const tab = new Tab("term");
      tab.panes.push(new Pane(tab, cwd || this.focusedPane()?.cwd));
      this.tabs.push(tab);
      this.active = this.tabs.length - 1;
      this.layout();
      this.focusPane(tab.panes[0], giveFocus);
      return tab;
    },
    openViewer(url, name) {
      const tab = new Tab("viewer", { url, name });
      this.tabs.push(tab);
      this.active = this.tabs.length - 1;
      this.layout();
    },
    split(direction) {
      const tab = this.currentTab();
      if (!tab || tab.kind !== "term") return;
      if (tab.panes.length >= 4) { this.showToast("Até 4 painéis por aba"); return; }
      if (tab.panes.length === 1) tab.direction = direction;
      const pane = new Pane(tab, tab.panes[tab.focused].cwd);
      tab.panes.splice(tab.focused + 1, 0, pane);
      tab.focused += 1;
      this.layout();
      this.focusPane(pane, true);
    },
    closePane(pane) {
      const tab = pane ? pane.tab : this.currentTab();
      if (!tab) return;
      if (tab.kind === "term" && tab.panes.length > 1) {
        const index = tab.panes.indexOf(pane || tab.panes[tab.focused]);
        tab.panes.splice(index, 1);
        tab.focused = Math.min(index, tab.panes.length - 1);
        this.layout();
        this.focusPane(tab.panes[tab.focused], true);
        return;
      }
      this.closeTab(this.tabs.indexOf(tab));
    },
    closeTab(index) {
      const tab = this.tabs[index];
      if (!tab) return;
      tab.panes.forEach((p) => { p.aborted = true; p.waitingKey = false; });
      this.tabs.splice(index, 1);
      if (!this.tabs.length) {
        this.newTab(`${HOME}/hacker-terminal`);
        this.focusedPane().write("A última aba foi fechada; no app, a janela fecharia. Aqui, começamos de novo.\n", "c8");
        this.focusedPane().renderInput();
        return;
      }
      this.active = Math.min(this.active > index ? this.active - 1 : this.active, this.tabs.length - 1);
      this.layout();
      const pane = this.focusedPane();
      if (pane) this.focusPane(pane, true);
    },
    switchTab(index) {
      this.active = (index + this.tabs.length) % this.tabs.length;
      this.layout();
      const pane = this.focusedPane();
      if (pane) this.focusPane(pane, true);
    },
    focusPane(pane, giveFocus) {
      const tab = pane.tab;
      tab.focused = tab.panes.indexOf(pane);
      tab.panes.forEach((p) => {
        p.node.classList.toggle("focused", p === pane);
        p.node.classList.toggle("inactive", p !== pane && tab.panes.length > 1);
      });
      this.input.value = pane.buffer;
      try { this.input.setSelectionRange(pane.caret, pane.caret); } catch { /* not focusable yet */ }
      if (giveFocus) this.input.focus({ preventScroll: true });
      this.refreshChrome();
    },
    layout() {
      const tab = this.currentTab();
      this.panesNode.replaceChildren();
      this.panesNode.style.cssText = "";
      this.fx.hidden = tab.kind === "viewer";  // effects belong to the terminal, not the image viewer
      if (tab.kind === "viewer") {
        this.panesNode.append(el("div", { class: "ht-pane", style: "display:grid;place-items:center;padding:16px;overflow:auto" },
          el("img", { src: tab.url, alt: tab.name, style: "max-width:100%;max-height:100%;border-radius:4px" })));
      } else {
        const n = tab.panes.length;
        const areas = n === 1 ? ['"a"'] : n === 2 ? (tab.direction === "h" ? ['"a b"'] : ['"a"', '"b"'])
          : n === 3 ? (tab.direction === "h" ? ['"a b"', '"a c"'] : ['"a a"', '"b c"']) : ['"a b"', '"c d"'];
        const cols = areas[0].split(" ").length;
        this.panesNode.style.gridTemplateAreas = areas.join(" ");
        this.panesNode.style.gridTemplateColumns = `repeat(${cols}, minmax(0, 1fr))`;
        this.panesNode.style.gridTemplateRows = `repeat(${areas.length}, minmax(0, 1fr))`;
        tab.panes.forEach((pane, index) => {
          pane.node.style.gridArea = "abcd"[index];
          this.panesNode.append(pane.node);
          pane.renderInput();
        });
        this.focusPane(tab.panes[tab.focused]);
      }
      this.renderTabs();
      this.refreshChrome();
    },
    renderTabs() {
      this.tabBar.hidden = this.tabs.length < 2;
      this.tabBar.replaceChildren(...this.tabs.map((tab, index) => el("button", {
        type: "button", role: "tab", class: `ht-tab${index === this.active ? " active" : ""}${tab.broadcast ? " broadcast" : ""}`,
        "aria-selected": String(index === this.active), onclick: () => this.switchTab(index),
      }, tab.kind === "viewer" ? `🖼 ${tab.title()}` : tab.title(), el("span", {
        class: "x", role: "button", "aria-label": "Fechar aba", title: "Fechar aba",
        onclick: (event) => { event.stopPropagation(); this.closeTab(index); },
      }, "×"))));
    },
    refreshChrome() {
      const tab = this.currentTab();
      if (!tab) return;
      const pane = this.focusedPane();
      this.title.textContent = pane ? `${USER}@${HOST}: ${shortPath(pane.cwd)}` : `Visualizador: ${tab.name}`;
      this.statusLeft.textContent = pane ? shortPath(pane.cwd) : tab.name;
      const right = [];
      if (pane && pane.failedCode) right.push(el("span", { class: "warn", text: `✗ saída ${pane.failedCode}` }));
      if (tab.broadcast) right.push(el("span", { class: "warn", text: `⇉ TRANSMITINDO PARA ${tab.panes.length}` }));
      right.push(el("span", { text: `${this.tabs.length} ${this.tabs.length === 1 ? "aba" : "abas"}` }));
      if (pane && inRepo(pane.cwd)) right.push(el("span", { text: "git main" }));
      this.statusRight.replaceChildren(...right.flatMap((node, index) => (index ? [el("span", { class: "sep" }), node] : [node])));
      this.work.classList.toggle("broadcast", Boolean(tab.broadcast));
      if (this.tabs.length > 1) this.renderTabs();
    },

    /* settings */
    set(patch) {
      const before = { ...state };
      Object.assign(state, patch);
      if ("theme" in patch || "fontSize" in patch || "effects" in patch || "sound" in patch || "panel" in patch) {
        if (!("profile" in patch)) state.profile = this.matchingProfile();
      }
      if (patch.sound && (!before.sound || before.pack !== state.pack)) { const pack = PACKS.get(state.pack); if (pack) sound.load(pack); }
      if ("volume" in patch && sound.gain) sound.gain.gain.value = (state.volume / 100) ** 1.6;
      this.apply();
    },
    matchingProfile() {
      for (const profile of PROFILES.values()) {
        if (profile.theme === state.theme && profile.font_size === state.fontSize && profile.effects === state.effects
          && profile.sound === state.sound && profile.panel === state.panel) return profile.id;
      }
      return "";
    },
    applyProfile(id) {
      const profile = PROFILES.get(id);
      if (!profile) return;
      this.set({ profile: id, theme: profile.theme, fontSize: profile.font_size, effects: profile.effects, sound: profile.sound, panel: profile.panel });
    },
    setTheme(id) { this.set({ theme: id }); },
    zoom(step) {
      const size = step === 0 ? 11 : Math.max(8, Math.min(24, state.fontSize + step));
      this.set({ fontSize: size });
    },
    charWidth() {
      if (!this.measure) {
        this.measure = el("span", { style: "position:absolute;visibility:hidden;white-space:pre" }, "M".repeat(20));
      }
      const screen = this.focusedPane()?.screen || this.root;
      screen.append(this.measure);
      const width = this.measure.getBoundingClientRect().width / 20 || 8;
      this.measure.remove();
      return width;
    },
    apply(previewTheme) {
      const theme = previewTheme || currentTheme();
      const style = this.root.style;
      const set = (name, value) => style.setProperty(name, value);
      Object.entries(theme.ui).forEach(([key, value]) => set(`--ui-${key === "background" ? "bg" : key === "foreground" ? "fg" : key}`, value));
      set("--t-bg", theme.term.background);
      set("--t-fg", theme.term.foreground);
      set("--t-cursor", theme.term.cursor);
      set("--t-sel-bg", theme.term.selection_background);
      set("--t-sel-fg", theme.term.selection_foreground);
      theme.ansi.forEach((color, index) => set(`--c${index}`, color));
      set("--hairline", mix(theme.ui.border, theme.term.background, 0.65));
      set("--raised", mix(theme.ui.foreground, theme.ui.surface, 0.05));
      set("--accent-soft", mix(theme.ui.accent, theme.ui.surface, 0.18));
      set("--inactive", contrast(theme.term.foreground, theme.term.background) >= 18 ? "1" : "0.62");
      const font = fontInfo(state.font);
      set("--font", font.css);
      set("--size", `${Math.round(state.fontSize * 1.2 * font.scale)}px`);
      const fx = theme.fx;
      const padding = fx.curvature ? Math.round(4 + 10 * fx.curvature) : 8;
      set("--pad", `${padding}px`);
      set("--tube-r", fx.curvature ? `${3 * padding}px` : "0px");
      set("--scan", String(fx.scanlines));
      set("--scan-gap", fx.scanlines >= 0.2 ? "3px" : "4px");
      set("--vignette", String(Math.min(0.9, fx.vignette * 0.9)));
      set("--glow", String(fx.glow));
      set("--noise", String(fx.noise * 0.55));
      set("--flicker", String(fx.flicker));
      set("--curve", String(fx.curvature));
      const [r, g, b] = rgb(theme.term.foreground);
      set("--glow-shadow", state.effects && fx.glow ? `0 0 ${(1 + 7 * fx.glow).toFixed(1)}px rgba(${r},${g},${b},${(0.2 + 0.55 * fx.glow).toFixed(2)})` : "none");
      this.root.classList.toggle("flicker", fx.flicker > 0);
      this.root.classList.toggle("noisy", fx.noise > 0);
      this.root.style.colorScheme = theme.dark ? "dark" : "light";
      this.panel.hidden = !state.panel;
      this.panelButton.setAttribute("aria-pressed", String(state.panel));
      this.previewing = previewTheme || null;
      this.updateEffects();
      this.tabs.forEach((tab) => tab.panes.forEach((pane) => pane.renderInput()));
      if (this.prefsRefresh) this.prefsRefresh();
    },
    updateEffects() {
      const theme = this.previewing || currentTheme();
      const on = state.effects || rain.boost;
      this.root.classList.toggle("fx-on", on);
      rain.update((state.effects && theme.fx.rain) || rain.boost, theme.fx.matrix);
    },

    /* history (Ctrl+Shift+H) */
    recordHistory(entry) {
      this.commandLog.push(entry);
      if (this.commandLog.length > 500) this.commandLog.shift();
    },

    /* keyboard */
    bindKeys() {
      const input = this.input;
      input.addEventListener("input", () => {
        const pane = this.focusedPane();
        if (!pane || pane.busy) { input.value = pane ? pane.buffer : ""; return; }
        pane.historyIndex = null;
        pane.setBuffer(input.value, input.selectionStart ?? input.value.length);
        const tab = pane.tab;
        if (tab.broadcast) tab.panes.forEach((p) => { if (p !== pane && !p.busy) p.setBuffer(input.value); });
      });
      input.addEventListener("keyup", (event) => { this.syncCaret(); if (soundKey(event)) sound.play("release", event.key); });
      input.addEventListener("select", () => this.syncCaret());
      input.addEventListener("keydown", (event) => this.onTerminalKey(event));
      this.root.addEventListener("keydown", (event) => {
        if (event.target === input || this.overlay) return;
        this.onShortcut(event);
      });
      // a dialog whose focused control was re-rendered away still closes with Esc
      document.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && this.overlay && (document.activeElement === document.body || this.root.contains(document.activeElement))) {
          event.preventDefault();
          this.closeOverlay();
        }
      });
    },
    syncCaret() {
      const pane = this.focusedPane();
      const input = this.input;
      if (pane && !pane.busy && input.selectionStart !== pane.caret) { pane.caret = input.selectionStart ?? pane.buffer.length; pane.renderInput(); }
    },
    onShortcut(event) {
      const ctrl = event.ctrlKey || event.metaKey;
      const key = event.key.length === 1 ? event.key.toLowerCase() : event.key;
      let action = null;
      if (ctrl && event.shiftKey) {
        action = {
          t: () => this.newTab(), w: () => this.closePane(this.focusedPane()), d: () => this.split("h"), e: () => this.split("v"),
          o: () => this.nextPane(), i: () => this.toggleBroadcast(), p: () => this.openPalette(), b: () => this.set({ panel: !state.panel }),
          h: () => this.openHistory(), l: () => this.copyLastOutput(), ArrowUp: () => this.focusedPane()?.jumpMark(-1),
          ArrowDown: () => this.focusedPane()?.jumpMark(1),
        }[key];
      } else if (ctrl && !event.altKey) {
        action = {
          ",": () => this.openPreferences(), "+": () => this.zoom(1), "=": () => this.zoom(1), "-": () => this.zoom(-1), 0: () => this.zoom(0),
          PageDown: () => this.switchTab(this.active + 1), PageUp: () => this.switchTab(this.active - 1),
        }[key];
      } else if (key === "F11") action = () => this.toggleFullscreen();
      if (!action) return false;
      event.preventDefault();
      event.stopPropagation();
      action();
      return true;
    },
    onTerminalKey(event) {
      const pane = this.focusedPane();
      if (!pane) return;
      if (!event.repeat && soundKey(event)) sound.play("press", event.key);
      if (this.onShortcut(event)) return;
      requestAnimationFrame(() => this.syncCaret());
      const ctrl = event.ctrlKey || event.metaKey;
      if (pane.waitingKey) { event.preventDefault(); pane.waitingKey = false; return; }
      if (ctrl && !event.shiftKey && event.key.toLowerCase() === "c" && !String(getSelection())) {
        event.preventDefault();
        if (pane.busy) { pane.aborted = true; return; }
        pane.write(pane.promptParts().map(([t]) => t).join("") + pane.buffer + "^C\n", "c8");
        pane.setBuffer("");
        this.input.value = "";
        return;
      }
      if (pane.busy) { if (event.key.length === 1 || event.key === "Enter") event.preventDefault(); return; }
      const broadcast = pane.tab.broadcast ? pane.tab.panes.filter((p) => p !== pane && !p.busy) : [];
      switch (event.key) {
        case "Enter": {
          event.preventDefault();
          const line = pane.buffer;
          this.input.value = "";
          pane.submit(line);
          broadcast.forEach((p) => p.submit(line));
          return;
        }
        case "Tab":
          event.preventDefault();
          pane.complete();
          this.input.value = pane.buffer;
          this.input.setSelectionRange(pane.caret, pane.caret);
          return;
        case "ArrowUp":
        case "ArrowDown":
          if (event.shiftKey || ctrl) return;
          event.preventDefault();
          pane.historyStep(event.key === "ArrowUp" ? -1 : 1);
          this.input.value = pane.buffer;
          this.input.setSelectionRange(pane.caret, pane.caret);
          return;
        case "ArrowRight": {
          const hint = pane.suggestion();
          if (hint && this.input.selectionStart === pane.buffer.length) {
            event.preventDefault();
            pane.setBuffer(pane.buffer + hint);
            this.input.value = pane.buffer;
          }
          return;
        }
        case "Escape":
          return;
        default:
          break;
      }
      if (ctrl && !event.shiftKey) {
        const key = event.key.toLowerCase();
        const edits = {
          l: () => { pane.clear(); pane.renderInput(); },
          u: () => pane.setBuffer(pane.buffer.slice(pane.caret), 0),
          a: () => pane.setBuffer(pane.buffer, 0),
          e: () => pane.setBuffer(pane.buffer),
          k: () => pane.setBuffer(pane.buffer.slice(0, pane.caret)),
          w: null,
        };
        if (edits[key]) {
          event.preventDefault();
          edits[key]();
          this.input.value = pane.buffer;
          this.input.setSelectionRange(pane.caret, pane.caret);
        }
      }
    },
    nextPane() {
      const tab = this.currentTab();
      if (tab.kind !== "term" || tab.panes.length < 2) return;
      this.focusPane(tab.panes[(tab.focused + 1) % tab.panes.length], true);
    },
    toggleBroadcast() {
      const tab = this.currentTab();
      if (tab.kind !== "term") return;
      tab.broadcast = !tab.broadcast;
      this.renderTabs();
      this.refreshChrome();
      this.showToast(tab.broadcast ? `Digitando em todos os ${tab.panes.length} painéis da aba` : "Digitação em todos os painéis desligada");
    },
    copyLastOutput() {
      const pane = this.focusedPane();
      if (!pane) return;
      copyText(pane.lastOutput).then((ok) => this.showToast(ok ? "Saída do último comando copiada" : "Não foi possível copiar"));
    },
    toggleFullscreen() {
      if (document.fullscreenElement) document.exitFullscreen();
      else if (this.root.requestFullscreen) this.root.requestFullscreen().catch(() => {});
    },
    showToast(text) {
      this.toast.textContent = text;
      this.toast.classList.add("show");
      clearTimeout(this.toastTimer);
      this.toastTimer = setTimeout(() => this.toast.classList.remove("show"), 2200);
    },

    /* type a command into the focused pane, as if the visitor had */
    async typeCommand(command) {
      let pane = this.focusedPane();
      if (!pane) { this.switchTab(this.tabs.findIndex((t) => t.kind === "term")); pane = this.focusedPane(); }
      if (!pane) return;
      if (pane.busy) { this.showToast("Aguarde o comando terminar (Ctrl+C para)"); return; }
      this.closeOverlay();
      const box = this.root.getBoundingClientRect();
      if (box.top < 0 || box.bottom > innerHeight) this.root.scrollIntoView({ block: "nearest", behavior: REDUCED_MOTION ? "auto" : "smooth" });
      this.input.focus({ preventScroll: true });
      if (this.typing) return;
      this.typing = true;
      pane.setBuffer("");
      for (const char of command) {
        pane.setBuffer(pane.buffer + char);
        sound.play("press", char);
        await sleep(REDUCED_MOTION ? 0 : 18 + Math.random() * 30);
        sound.play("release", char);
      }
      await sleep(120);
      sound.play("press", "Enter");
      this.input.value = "";
      this.typing = false;
      pane.submit(command);
    },

    /* dialogs */
    openOverlay(dialog, onClose) {
      this.closeOverlay();
      const overlay = el("div", { class: "ht-overlay", onmousedown: (event) => { if (event.target === overlay) this.closeOverlay(); } }, dialog);
      overlay.addEventListener("keydown", (event) => {
        if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); this.closeOverlay(); }
      });
      this.root.append(overlay);
      this.overlay = { node: overlay, onClose };
    },
    closeOverlay(keepFocus) {
      if (!this.overlay) return;
      const { node, onClose } = this.overlay;
      this.overlay = null;
      node.remove();
      this.prefsRefresh = null;
      if (onClose) onClose();
      if (!keepFocus && this.focusedPane()) this.input.focus({ preventScroll: true });
    },

    paletteEntries() {
      const entries = [];
      const add = (label, category, run, meta) => entries.push({ label, category, run, meta, search: normalize(`${label} ${category}`) });
      for (const theme of THEMES.values()) entries.push({ label: `Aplicar tema: ${theme.name}`, category: "Tema", theme, run: () => this.setTheme(theme.id), search: normalize(`aplicar tema ${theme.name} ${theme.id}`) });
      for (const profile of PROFILES.values()) add(`Aplicar perfil: ${profile.name}`, "Perfil", () => this.applyProfile(profile.id));
      for (const action of DATA.actions) add(action.label + (action.fields.length ? " …" : ""), "Ação", () => this.runAction(action));
      add("Nova aba", "Janela", () => this.newTab(), "Ctrl+Shift+T");
      add("Dividir lado a lado", "Janela", () => this.split("h"), "Ctrl+Shift+D");
      add("Dividir em cima e embaixo", "Janela", () => this.split("v"), "Ctrl+Shift+E");
      add("Fechar painel ou aba", "Janela", () => this.closePane(this.focusedPane()), "Ctrl+Shift+W");
      add("Próximo painel", "Janela", () => this.nextPane(), "Ctrl+Shift+O");
      add("Digitar em todos os painéis da aba", "Janela", () => this.toggleBroadcast(), "Ctrl+Shift+I");
      add("Mostrar ou ocultar ações", "Janela", () => this.set({ panel: !state.panel }), "Ctrl+Shift+B");
      add("Tela cheia", "Janela", () => this.toggleFullscreen(), "F11");
      add("Preferências", "Janela", () => this.openPreferences(), "Ctrl+,");
      add("Histórico de comandos", "Terminal", () => this.openHistory(), "Ctrl+Shift+H");
      add("Copiar saída do último comando", "Terminal", () => this.copyLastOutput(), "Ctrl+Shift+L");
      add("Limpar terminal", "Terminal", () => { const p = this.focusedPane(); if (p) { p.clear(); p.renderInput(); } });
      add(state.effects ? "Desligar efeitos visuais" : "Ligar efeitos visuais", "Aparência", () => this.set({ effects: !state.effects }));
      add(state.sound ? "Desligar som do teclado" : "Ligar som do teclado", "Som", () => this.set({ sound: !state.sound }));
      add("Aumentar fonte", "Aparência", () => this.zoom(1), "Ctrl++");
      add("Diminuir fonte", "Aparência", () => this.zoom(-1), "Ctrl+-");
      return entries;
    },
    openPalette() {
      const entries = this.paletteEntries();
      let chosen = false;
      let shown = [];
      let selected = 0;
      let previewTimer = 0;
      const search = el("input", { type: "search", placeholder: "Pesquisar ações, perfis e temas…", "aria-label": "Pesquisar na paleta", autocomplete: "off" });
      const list = el("ul", { class: "ht-list", role: "listbox", "aria-label": "Resultados" });
      const preview = () => {
        clearTimeout(previewTimer);
        const entry = shown[selected];
        previewTimer = setTimeout(() => this.apply(entry && entry.theme ? entry.theme : null), 90);
      };
      const choose = (entry) => {
        if (!entry) return;
        chosen = true;
        clearTimeout(previewTimer);
        this.closeOverlay(true);
        entry.run();
        if (!this.overlay && this.focusedPane()) this.input.focus({ preventScroll: true });
      };
      const render = () => {
        const words = normalize(search.value).split(/\s+/).filter(Boolean);
        shown = entries.filter((entry) => words.every((w) => entry.search.includes(w)));
        selected = Math.min(selected, Math.max(0, shown.length - 1));
        list.replaceChildren(...shown.slice(0, 80).map((entry, index) => el("li", {
          role: "option", "aria-selected": String(index === selected),
          onmousemove: () => { if (selected !== index) { selected = index; highlight(); } },
          onclick: () => choose(entry),
        }, el("span", { text: entry.label }), el("span", { style: "display:flex;gap:8px;align-items:center" },
          entry.meta ? el("span", { class: "meta", text: entry.meta }) : null, el("span", { class: "cat", text: entry.category })))));
        if (!shown.length) list.append(el("li", { "aria-disabled": "true", style: "cursor:default;color:var(--ui-muted)" }, "Nada encontrado"));
        preview();
      };
      const highlight = () => {
        [...list.children].forEach((item, index) => item.setAttribute("aria-selected", String(index === selected)));
        reveal(list, list.children[selected]);
        preview();
      };
      search.addEventListener("input", () => { selected = 0; render(); });
      search.addEventListener("keydown", (event) => {
        if (event.key === "ArrowDown" || event.key === "ArrowUp") {
          event.preventDefault();
          selected = Math.max(0, Math.min(shown.length - 1, selected + (event.key === "ArrowDown" ? 1 : -1)));
          highlight();
        } else if (event.key === "Enter") { event.preventDefault(); choose(shown[selected]); }
      });
      const dialog = el("div", { class: "ht-dialog", role: "dialog", "aria-label": "Paleta de comandos" },
        search, list,
        el("div", { class: "ht-row spread" }, el("span", { class: "sub", text: "↑↓ escolhe · o tema aparece na hora · Esc volta ao anterior" }),
          el("button", { type: "button", class: "ht-action", onclick: () => this.closeOverlay() }, "Fechar")));
      this.openOverlay(dialog, () => {
        clearTimeout(previewTimer);
        if (!chosen) this.apply();  // the preview never touched state.theme
      });
      render();
      search.focus({ preventScroll: true });
    },

    openPreferences(tabName = "Aparência") {
      const tabs = ["Geral", "Aparência", "Terminal", "Som do teclado", "Atalhos"];
      let currentTab = tabName;
      const tabBar = el("div", { class: "ht-prefs-tabs", role: "tablist" });
      const body = el("div", { class: "ht-prefs-body" });
      const field = (label, ...controls) => el("div", { class: "ht-field" }, el("span", { text: label }), el("div", {}, ...controls));
      const check = (label, key) => el("label", {}, el("input", { type: "checkbox", "aria-label": label, checked: state[key], onchange: (e) => this.set({ [key]: e.target.checked }) }), label);
      const select = (options, value, onchange, label) => {
        const node = el("select", { "aria-label": label, onchange: (e) => onchange(e.target.value) },
          ...options.map(([v, text]) => el("option", { value: v, selected: v === value }, text)));
        return node;
      };
      const pages = {
        Geral: () => [
          field("Perfil", select([["", "— personalizado —"], ...[...PROFILES.values()].map((p) => [p.id, p.name])], state.profile, (id) => id && this.applyProfile(id), "Perfil")),
          el("p", { class: "ht-hint", text: PROFILES.get(state.profile)?.description || "As configurações atuais não batem com nenhum perfil. No app, “Salvar como perfil…” guarda este conjunto." }),
          field("Painel lateral", check("Mostrar as ações rápidas", "panel")),
          field("Integração com o shell", check("Marcar cada comando na margem (vermelho se falhou)", "marks")),
        ],
        Aparência: () => {
          const theme = currentTheme();
          const suggested = theme.font && WEB_FONT_FOR[theme.font];
          return [
            field("Tema", select([...THEMES.values()].map((t) => [t.id, t.name]), state.theme, (id) => this.setTheme(id), "Tema")),
            field("Cores", el("div", { class: "ht-preview" }, ...theme.ansi.map((color) => el("i", { style: `background:${color}`, title: color })))),
            field("Fonte", select(FONTS.map((f) => [f.name, f.name]), state.font, (name) => this.set({ font: name }), "Fonte"),
              suggested && suggested !== state.font
                ? el("div", { class: "ht-hint", style: "margin-top:6px" }, `O tema sugere ${theme.font}. `,
                  el("button", { type: "button", class: "ht-action", style: "min-height:26px;padding:0 10px", onclick: () => this.set({ font: suggested }) }, `Usar ${suggested}`))
                : null),
            field(`Tamanho: ${state.fontSize}`, el("input", { type: "range", min: 8, max: 24, value: state.fontSize, "aria-label": "Tamanho da fonte", oninput: (e) => this.set({ fontSize: Number(e.target.value) }) })),
            field("Efeitos visuais", check("Brilho, scanlines, chuva digital e visual CRT", "effects")),
            el("p", { class: "ht-hint", text: `Este tema: ${[theme.fx.rain && "chuva digital", theme.fx.glow && "brilho", theme.fx.scanlines >= 0.05 && "scanlines", theme.fx.curvature && "curvatura do tubo", theme.fx.noise && "ruído", theme.fx.flicker && "cintilação", theme.fx.vignette && "vinheta"].filter(Boolean).join(", ") || "sem efeitos"}.` }),
          ];
        },
        Terminal: () => [
          field("Formato do cursor", ...Object.entries(CURSORS).map(([shape, label]) => el("label", {},
            el("input", { type: "radio", name: "ht-cursor", "aria-label": label, checked: state.cursor === shape, onchange: () => this.set({ cursor: shape }) }), label))),
          field("Piscar", check("Cursor piscando", "blink")),
          field("Histórico", el("span", { class: "ht-hint", text: "20 mil linhas (até 200 mil no app)" })),
        ],
        "Som do teclado": () => [
          field("Som", check("Tocar o som do teclado ao digitar", "sound")),
          field("Switch", select([...PACKS.values()].map((p) => [p.id, p.name]), state.pack, (id) => this.set({ pack: id, sound: true }), "Pacote de som")),
          field(`Volume: ${state.volume}%`, el("input", { type: "range", min: 0, max: 100, value: state.volume, "aria-label": "Volume", oninput: (e) => this.set({ volume: Number(e.target.value) }) })),
          field("Ao soltar", check("Tocar também o som de subida da tecla", "keyRelease")),
          field("Teste", (() => {
            const test = el("input", { type: "text", placeholder: "Digite aqui para ouvir…", "aria-label": "Campo de teste do som" });
            test.addEventListener("keydown", (e) => { if (!e.repeat && soundKey(e)) { if (!state.sound) this.set({ sound: true }); sound.play("press", e.key); } });
            test.addEventListener("keyup", (e) => { if (soundKey(e)) sound.play("release", e.key); });
            return test;
          })()),
          el("p", { class: "ht-hint", text: `Gravações reais do Mechvibes (MIT). O app traz 18 pacotes e os switches sintetizados Red, Brown e Blue; aqui estão ${PACKS.size}.` }),
        ],
        Atalhos: () => [
          el("div", { class: "ht-keys" }, ...SHORTCUTS.map(([label, keys]) => el("div", {}, el("span", { text: label }), el("kbd", { text: keys })))),
          el("p", { class: "ht-hint", text: "No app, todos podem ser trocados: clique e pressione a nova combinação. No navegador, alguns (como Ctrl+Shift+T e Ctrl+Shift+W) pertencem ao próprio navegador; use os botões." }),
        ],
      };
      const render = () => {
        const active = document.activeElement;
        const focusedId = active && body.contains(active) ? active.getAttribute("aria-label") : null;
        const onTabs = active && tabBar.contains(active);
        tabBar.replaceChildren(...tabs.map((name) => el("button", { type: "button", role: "tab", "aria-selected": String(name === currentTab), onclick: () => { currentTab = name; render(); } }, name)));
        body.replaceChildren(...pages[currentTab]());
        if (focusedId) body.querySelector(`[aria-label="${focusedId}"]`)?.focus({ preventScroll: true });
        if (onTabs) tabBar.querySelector('[aria-selected="true"]').focus({ preventScroll: true });
      };
      const dialog = el("div", { class: "ht-dialog ht-prefs", role: "dialog", "aria-label": "Preferências" },
        el("h4", { text: "Preferências" }), tabBar, body,
        el("div", { class: "ht-row spread" },
          el("span", { class: "sub", text: "Tudo é aplicado na hora. Veja o resultado em ~/.config/hacker-terminal/config.ini" }),
          el("button", { type: "button", class: "ht-action primary", onclick: () => this.closeOverlay() }, "Fechar")));
      this.openOverlay(dialog);
      this.prefsRefresh = () => { if (!["range", "text"].includes(document.activeElement?.type)) render(); };
      render();
      tabBar.querySelector('[aria-selected="true"]').focus({ preventScroll: true });
    },

    openHistory() {
      let onlyFailures = false;
      let repeated = false;
      let selected = 0;
      let shown = [];
      const search = el("input", { type: "search", placeholder: "Buscar comandos, pastas e lugares…", "aria-label": "Buscar no histórico" });
      const list = el("ul", { class: "ht-list", role: "listbox", "aria-label": "Comandos" });
      const use = () => {
        const entry = shown[selected];
        if (!entry) return;
        this.closeOverlay();
        const pane = this.focusedPane();
        if (pane && !pane.busy) { pane.setBuffer(entry.command); this.input.value = entry.command; }
      };
      const ago = (date) => {
        const seconds = Math.round((Date.now() - date) / 1000);
        return seconds < 60 ? `há ${seconds} s` : `há ${Math.round(seconds / 60)} min`;
      };
      const render = () => {
        const words = normalize(search.value).split(/\s+/).filter(Boolean);
        const seen = new Set();
        shown = [...this.commandLog].reverse().filter((entry) => {
          if (onlyFailures && entry.code === 0) return false;
          if (!repeated) { if (seen.has(entry.command)) return false; seen.add(entry.command); }
          const text = normalize(`${entry.command} ${entry.cwd} ${entry.place}`);
          return words.every((w) => text.includes(w));
        });
        selected = Math.min(selected, Math.max(0, shown.length - 1));
        list.replaceChildren(...shown.map((entry, index) => el("li", {
          role: "option", "aria-selected": String(index === selected), onclick: () => { selected = index; render(); }, ondblclick: use,
        }, el("span", { style: "display:flex;gap:10px;min-width:0;align-items:center" },
          el("span", { class: entry.code ? "bad" : "good", text: entry.code ? `✗ ${entry.code}` : "✓" }),
          el("code", { text: entry.command, style: "overflow:hidden;text-overflow:ellipsis;white-space:nowrap" })),
        el("span", { class: "meta", text: `${ago(entry.when)} · ${entry.duration < 1000 ? Math.round(entry.duration) + " ms" : (entry.duration / 1000).toFixed(1).replace(".", ",") + " s"} · ${entry.cwd}` }))));
        if (!shown.length) list.append(el("li", { style: "cursor:default;color:var(--ui-muted)" }, this.commandLog.length ? "Nenhum comando combina com a busca" : "Rode alguns comandos: eles aparecem aqui, de todas as abas"));
      };
      search.addEventListener("input", () => { selected = 0; render(); });
      search.addEventListener("keydown", (event) => {
        if (event.key === "ArrowDown" || event.key === "ArrowUp") {
          event.preventDefault();
          selected = Math.max(0, Math.min(shown.length - 1, selected + (event.key === "ArrowDown" ? 1 : -1)));
          render();
          reveal(list, list.children[selected]);
        } else if (event.key === "Enter") { event.preventDefault(); use(); }
      });
      const toggle = (label, onchange) => el("label", { style: "display:inline-flex;gap:6px;align-items:center;font-size:13px;cursor:pointer" },
        el("input", { type: "checkbox", onchange: (e) => { onchange(e.target.checked); render(); } }), label);
      const dialog = el("div", { class: "ht-dialog", role: "dialog", "aria-label": "Histórico de comandos" },
        el("h4", { text: "Histórico de comandos" }), search,
        el("div", { class: "ht-row spread" }, el("span", { style: "display:flex;gap:14px" }, toggle("Só falhas", (v) => { onlyFailures = v; }), toggle("Mostrar repetidos", (v) => { repeated = v; })),
          el("span", { class: "sub", text: "de todas as abas e painéis" })),
        list,
        el("div", { class: "ht-row" },
          el("button", { type: "button", class: "ht-action", onclick: () => { const e = shown[selected]; if (e) copyText(e.command).then((ok) => this.showToast(ok ? "Comando copiado" : "Não foi possível copiar")); } }, "Copiar"),
          el("button", { type: "button", class: "ht-action", onclick: () => this.closeOverlay() }, "Fechar"),
          el("button", { type: "button", class: "ht-action primary", onclick: use }, "Usar no terminal")));
      this.openOverlay(dialog);
      render();
      search.focus({ preventScroll: true });
    },

    runAction(action) {
      if (action.in_terminal) { this.typeCommand(action.command); return; }
      if (action.fields.length) { this.askFields(action); return; }
      this.showResult(action, action.command);
    },
    askFields(action) {
      const values = (this.fieldMemory ||= {});
      const inputs = action.fields.map((f) => el("input", {
        type: "text", value: values[f.name] || "", placeholder: f.default != null ? `padrão: ${f.default || "vazio"}` : "obrigatório",
        "aria-label": f.name, oninput: () => update(),
      }));
      const preview = el("code", { style: "display:block;padding:8px 10px;border-radius:6px;background:var(--t-bg);color:var(--t-fg);white-space:pre-wrap;overflow-wrap:anywhere" });
      const run = el("button", { type: "button", class: "ht-action primary", onclick: () => submit() }, "Executar");
      const collect = () => Object.fromEntries(action.fields.map((f, i) => [f.name, inputs[i].value.trim()]));
      const update = () => {
        preview.textContent = fillFields(action.command, collect());
        run.disabled = action.fields.some((f, i) => f.default == null && !inputs[i].value.trim());
      };
      const submit = () => {
        if (run.disabled) return;
        Object.assign(values, collect());
        const command = fillFields(action.command, collect());
        this.closeOverlay(true);
        this.showResult(action, command);
      };
      const dialog = el("div", { class: "ht-dialog", role: "dialog", "aria-label": action.label },
        el("h4", { text: action.label }),
        el("span", { class: "sub", text: "Os valores entram protegidos por aspas: “10.0.0.5; rm -rf ~” vira um único argumento e nunca é executado." }),
        ...action.fields.map((f, i) => el("div", { class: "ht-field" }, el("span", { text: f.name }), inputs[i])),
        el("span", { class: "sub", text: "Comando final:" }), preview,
        el("div", { class: "ht-row" }, el("button", { type: "button", class: "ht-action", onclick: () => this.closeOverlay() }, "Cancelar"), run));
      dialog.addEventListener("keydown", (event) => { if (event.key === "Enter") { event.preventDefault(); submit(); } });
      this.openOverlay(dialog);
      update();
      const firstRequired = action.fields.findIndex((f) => f.default == null);
      inputs[Math.max(0, firstRequired)].focus({ preventScroll: true });
    },
    showResult(action, command) {
      const base = this.focusedPane() || { cwd: HOME, env: {} };
      const session = { cwd: base.cwd, oldCwd: null, env: { ...base.env, HOME, USER }, history: this.sharedHistory, lastCode: 0, aborted: false, pane: null, columns: () => 80 };
      const output = el("pre", { "aria-live": "polite" });
      const status = el("span", { class: "state", text: "rodando…" });
      const stop = el("button", { type: "button", class: "ht-action", onclick: () => { session.aborted = true; } }, "Parar");
      let text = "";
      const sink = { write: (chunk) => { text += chunk; output.textContent = text.replace(/^\n+/, ""); output.scrollTop = output.scrollHeight; } };
      const dialog = el("div", { class: "ht-dialog ht-result", role: "dialog", "aria-label": action.label },
        el("h4", { text: action.label }), el("code", { class: "sub", style: "background:none;padding:0", text: command }),
        output,
        el("div", { class: "ht-row spread" }, status, el("span", { class: "ht-row" },
          stop,
          el("button", { type: "button", class: "ht-action", onclick: () => copyText(text).then((ok) => this.showToast(ok ? "Saída copiada" : "Não foi possível copiar")) }, "Copiar"),
          el("button", { type: "button", class: "ht-action", onclick: () => { session.aborted = true; this.typeCommand(command); } }, "Rodar no terminal"),
          el("button", { type: "button", class: "ht-action primary", onclick: () => this.closeOverlay() }, "Fechar"))));
      this.openOverlay(dialog, () => { session.aborted = true; });
      dialog.querySelector(".primary").focus({ preventScroll: true });
      const startedAt = performance.now();
      runLine(session, command, { out: sink, err: sink, tty: false }).then((code) => {
        const seconds = ((performance.now() - startedAt) / 1000).toFixed(1).replace(".", ",");
        stop.disabled = true;
        if (session.aborted) { status.textContent = `■ interrompido · ${seconds} s`; status.className = "state fail"; return; }
        status.textContent = code === 0 ? `✓ concluído · código 0 · ${seconds} s` : `✗ falhou · código ${code} · ${seconds} s`;
        status.className = `state ${code === 0 ? "ok" : "fail"}`;
        this.recordHistory({ command, code, duration: performance.now() - startedAt, cwd: shortPath(session.cwd), when: new Date(), place: "ação rápida" });
      });
    },

    start() {
      this.build();
      this.apply();
      const tab = this.newTab(`${HOME}/hacker-terminal`, false);
      const pane = tab.panes[0];
      pane.write(`Hacker Terminal ${VERSION} · demonstração no navegador\n`, "c8");
      pane.write("Digite ", "c8");
      pane.write("help", "c2");
      pane.write(" para ver os comandos. Tab completa, ↑ recupera o histórico.\n\n", "c8");
      pane.submit("ls").then(() => pane.submit("git log --oneline -3"));
      document.getElementById("demo-try")?.addEventListener("click", (event) => {
        const button = event.target.closest("[data-run]");
        if (button) this.typeCommand(button.dataset.run);
      });
    },
  };

  app.start();
})();
