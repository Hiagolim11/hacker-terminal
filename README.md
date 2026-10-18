<div align="center">

<img src="assets/hacker-terminal.svg" alt="Hacker Terminal" width="112">

# Hacker Terminal

**Um terminal nativo para Linux, rápido e totalmente personalizável — com alma retrô.**

GTK 3 · VTE · Python · sem Electron, sem navegador, sem telemetria

[![CI](https://github.com/Hiagolim11/hacker-terminal/actions/workflows/ci.yml/badge.svg)](https://github.com/Hiagolim11/hacker-terminal/actions/workflows/ci.yml)
[![Site](https://img.shields.io/badge/site-hiagolim11.github.io-111111)](https://hiagolim11.github.io/hacker-terminal/)
[![Release](https://img.shields.io/github/v/release/Hiagolim11/hacker-terminal?color=29ff9a&label=vers%C3%A3o)](https://github.com/Hiagolim11/hacker-terminal/releases/latest)
[![Licença MIT](https://img.shields.io/badge/licen%C3%A7a-MIT-blue)](LICENSE)
![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-3776ab?logo=python&logoColor=white)
![GTK 3 + VTE](https://img.shields.io/badge/GTK%203-VTE%202.91-4a86cf?logo=gnome&logoColor=white)
![Linux](https://img.shields.io/badge/plataforma-Linux-fcc624?logo=linux&logoColor=black)

[Instalação](#-instalação) ·
[Recursos](#-recursos) ·
[Personalização](#-personalização) ·
[Como funciona](#-como-funciona) ·
[Solução de problemas](#-solução-de-problemas)

<br>

<img src="docs/screenshots/hero.png" alt="Hacker Terminal no tema Zero Day: um comando que falhou ganha a marca vermelha na margem e o código de saída na barra de status" width="100%">

</div>

---

## 📖 Sumário

- [O que é](#-o-que-é)
- [Recursos](#-recursos)
- [Galeria](#-galeria)
- [Instalação](#-instalação)
- [Primeiros passos](#-primeiros-passos)
- [Atalhos de teclado](#️-atalhos-de-teclado)
- [Personalização](#-personalização)
  - [Temas e editor visual](#temas-e-editor-visual)
  - [Perfis](#perfis)
  - [Som de teclado mecânico](#som-de-teclado-mecânico)
  - [Atalhos personalizados](#atalhos-personalizados)
  - [Ações rápidas](#ações-rápidas)
- [Painéis, avisos e gravação](#-painéis-avisos-e-gravação)
- [Visualizar imagens e planilhas](#️-visualizar-imagens-e-planilhas)
- [Referência de configuração](#️-referência-de-configuração)
- [Linha de comando](#-linha-de-comando)
- [Como funciona](#-como-funciona)
- [Segurança e privacidade](#-segurança-e-privacidade)
- [Solução de problemas](#-solução-de-problemas)
- [Desenvolvimento](#️-desenvolvimento)
- [Licença](#-licença)

---

## 💡 O que é

O **Hacker Terminal** é um emulador de terminal **de verdade** — não uma simulação. Ele roda o seu shell de login (`zsh`, `bash`, `fish`…) dentro de um PTY usando o **VTE**, o mesmo motor do GNOME Terminal e do Tilix. Por isso `vim`, `tmux`, `htop`, prompts Powerline, cores de 24 bits e programas de tela cheia funcionam exatamente como esperado.

Por cima desse motor maduro, ele adiciona uma camada pensada para quem passa o dia no terminal: abas e painéis divididos, paleta de comandos, temas editáveis, perfis, atalhos remapeáveis, ações rápidas, som de teclado mecânico de baixa latência e, se você quiser, a estética retrô completa, com chuva digital, scanlines e temas de tubo CRT.

> [!NOTE]
> O padrão é **sóbrio** (tema Minimal Dark, sem animações nem som). Toda a parte "hacker" é opcional e fica a um clique no perfil **Retro Hacker**.

---

## ✨ Recursos

<table>
<tr>
<td width="50%" valign="top">

### 🖥️ Terminal
- Shell de login real em PTY (VTE 2.91)
- Abas reordenáveis com títulos dinâmicos
- Divisões aninhadas: até 4 painéis por aba (grade 2×2)
- Aviso quando um comando longo termina em outra aba
- Salvar ou gravar a saída em `.txt` ou `.html` colorido
- Histórico de 20 mil linhas (até 200 mil)
- Pesquisa no histórico com navegação
- Links clicáveis com `Ctrl+clique`
- Copiar/colar, zoom, tela cheia
- Restauração da sessão e salvamento automático

</td>
<td width="50%" valign="top">

### 🎨 Aparência
- 22 temas internos — modernos (Zero Day, Neon Noir, Pôr do Sol Synth, Aurora, Grafite), 8 **Fósforo** no estilo Cool Retro Term, claros e de alto contraste — e temas próprios
- Imagem de fundo atrás do texto, com opacidade e encaixe ajustáveis
- **Editor visual de temas** (interface, terminal e 16 cores ANSI)
- Detecção automática de **Nerd Fonts** e glifos Powerline
- Cursor, negrito e opacidade configuráveis
- Interface minimalista: o terminal ocupa a janela inteira, o cabeçalho tem só quatro botões e o painel lateral fica guardado até você chamar (`Ctrl+Shift+B`)
- Layout responsivo: em janelas estreitas o painel se recolhe e o botão o mostra por cima
- Visual de **monitor CRT**: brilho do fósforo, curvatura, vinheta, ruído e cintilação
- Efeitos retrô opcionais: chuva digital e scanlines
- Abertura rápida: o shell fica pronto em ~0,8 s, e novas janelas abrem em ~0,4 s

</td>
</tr>
<tr>
<td valign="top">

### ⚙️ Produtividade
- **Paleta de comandos** (`Ctrl+Shift+P`) com busca e **prévia ao vivo dos temas**: o tema selecionado aparece na hora e volta ao anterior se você fechar sem escolher
- **Atalhos 100% remapeáveis**, com detecção de conflitos
- **Perfis** que guardam tema, fonte, shell, cursor, diretório e ações
- **Ações rápidas** editáveis no painel lateral
- **Monitor de recursos** opcional: CPU, clock, temperatura, memória e GPU na barra de status, com gráficos do último minuto no painel
- **Visualizador de imagens e planilhas** em abas (`ht-open`)
- Barra de status com diretório, branch Git e virtualenv

</td>
<td valign="top">

### 🔊 Som e robustez
- **Som de teclado mecânico**: switches Red, Brown e Blue
- **18 gravações de teclados reais** do Mechvibes já incluídas (Cherry MX, Topre, Holy Pandas, NK Cream, EG…), e importação de outros pacotes
- Motor de áudio de ~18 ms de latência
- Confirmação de **colagem perigosa**
- Log rotativo, captura de falhas e modo `--debug`
- Configuração atômica, tolerante a arquivos corrompidos

</td>
</tr>
</table>

---

## 🖼️ Galeria

<div align="center">

**Temas Fósforo** — inspirados no Cool Retro Term, com brilho, curvatura do tubo, vinheta e ruído

<img src="docs/screenshots/phosphor.png" alt="Os oito temas Fósforo" width="100%">

<br><br>

**Temas clássicos** — Matrix Green, Cyberpunk Purple e Ice Blue (além de Minimal Dark e Amber CRT)

<img src="docs/screenshots/themes.png" alt="Os temas clássicos Matrix Green, Cyberpunk Purple e Ice Blue" width="100%">

<br><br>

**Grade de até 4 painéis por aba, cada um com seu nome**

<img src="docs/screenshots/grid.png" alt="Grade 2x2 de painéis no tema Fósforo Verde, com os nomes projeto, alvos, notas e git" width="100%">

<br><br>

**Painéis divididos, abas e pesquisa no histórico**

<img src="docs/screenshots/split.png" alt="Dois painéis lado a lado no tema Cyberpunk Purple, com a pesquisa destacando a palavra Verde" width="100%">

<br><br>

**Paleta de comandos**

<img src="docs/screenshots/palette.png" alt="Paleta de comandos" width="100%">

<br><br>

<table>
<tr>
<td align="center"><b>Som do teclado</b><br><img src="docs/screenshots/prefs-sound.png" alt="Preferências de som" width="100%"></td>
<td align="center"><b>Atalhos remapeáveis</b><br><img src="docs/screenshots/prefs-shortcuts.png" alt="Editor de atalhos" width="100%"></td>
</tr>
<tr>
<td align="center"><b>Perfis personalizados</b><br><img src="docs/screenshots/prefs-general.png" alt="Perfis" width="100%"></td>
<td align="center"><b>Editor de temas</b><br><img src="docs/screenshots/theme-editor.png" alt="Editor de temas" width="100%"></td>
</tr>
</table>

</div>

---

## 📦 Instalação

### Requisitos

| Componente | Versão | Pacote (Debian/Ubuntu/Kali) | Obrigatório |
| --- | --- | --- | :---: |
| Python | 3.10+ | `python3` | ✅ |
| PyGObject | — | `python3-gi`, `python3-gi-cairo` | ✅ |
| GTK | 3.24 | `gir1.2-gtk-3.0` | ✅ |
| VTE | 2.91 | `gir1.2-vte-2.91` | ✅ |
| GStreamer | 1.x | `python3-gst-1.0`, `gstreamer1.0-plugins-base`, `gstreamer1.0-plugins-good` | 🔊 só para sons |
| Nerd Font | — | ex.: [JetBrainsMono Nerd Font](https://www.nerdfonts.com/) | 💎 recomendada |

Desenvolvido e testado no Kali Linux (XFCE em X11, PipeWire) com GTK 3.24 e VTE 0.84. Deve funcionar em outras distribuições com GTK 3 e VTE 2.91; Wayland ainda não foi testado.

### Opção 1 — Pacote `.deb` (recomendado)

Baixe o arquivo `hacker-terminal_*_all.deb` da [página de releases](https://github.com/Hiagolim11/hacker-terminal/releases/latest) e instale com o `apt`, que resolve as dependências sozinho:

```bash
sudo apt install ./hacker-terminal_*_all.deb
```

O terminal aparece no menu de aplicativos e fica disponível como `hacker-terminal`. Para atualizar, instale o `.deb` mais novo da mesma forma; para remover, `sudo apt remove hacker-terminal`.

### Opção 2 — Instalação só para o seu usuário (sem `sudo` para o app)

```bash
sudo apt install python3 python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-vte-2.91 \
                 python3-gst-1.0 gstreamer1.0-plugins-base gstreamer1.0-plugins-good
git clone https://github.com/Hiagolim11/hacker-terminal.git
cd hacker-terminal
./install.sh
```

Instala em `~/.local`, cria o comando `hacker-terminal` e adiciona o atalho ao menu.

```bash
./install.sh --check       # confere a instalação
./install.sh --uninstall   # remove tudo
```

### Opção 3 — Rodar direto do código-fonte

```bash
git clone https://github.com/Hiagolim11/hacker-terminal.git
cd hacker-terminal
./run.sh
```

### Opção 4 — Gerar o próprio `.deb`

```bash
make deb                                   # cria dist/hacker-terminal_<versão>_all.deb
sudo apt install ./dist/hacker-terminal_*_all.deb
```

### Verificar a instalação

```bash
hacker-terminal --diagnose
```

```text
Hacker Terminal 0.22.0
GTK: 3.24.52
VTE: 0.84.1
Fonte selecionada: JetBrainsMono Nerd Font
Powerline: OK
Nerd Font: OK
Shell: /usr/bin/zsh
...
```

---

## 🚀 Primeiros passos

1. **Abra** pelo menu de aplicativos ou com `hacker-terminal`.
2. **Escolha um perfil** em `Ctrl+,` → *Geral*: *Desenvolvimento* (sóbrio), *Foco* (sem painel) ou *Retro Hacker* (chuva digital e scanlines).
3. **Experimente a paleta** com `Ctrl+Shift+P` e digite `tema`, `perfil` ou `dividir`.
4. **Divida a tela** com `Ctrl+Shift+D` e alterne entre os painéis com `Ctrl+Shift+O`.
5. **Ligue o som do teclado** em `Ctrl+,` → *Som do teclado* e teste no campo “Digite aqui para ouvir…”.

---

## ⌨️ Atalhos de teclado

Estes são os padrões — **todos podem ser alterados** em *Preferências → Atalhos*.

| Atalho | Ação | | Atalho | Ação |
| --- | --- | --- | --- | --- |
| `Ctrl+Shift+T` | Nova aba | | `Ctrl+Shift+C` | Copiar |
| `Ctrl+Shift+W` | Fechar painel/aba | | `Ctrl+Shift+V` | Colar |
| `Ctrl+Shift+D` | Dividir horizontalmente | | `Ctrl+Shift+F` | Pesquisar no histórico |
| `Ctrl+Shift+E` | Dividir verticalmente | | `Ctrl+Shift+P` | Paleta de comandos |
| `Ctrl+Shift+O` | Próximo painel da aba | | `Ctrl+Shift+B` | Mostrar/ocultar ações |
| `Ctrl+PageDown` | Próxima aba | | `Ctrl+,` | Preferências |
| `Ctrl+PageUp` | Aba anterior | | `F11` | Tela cheia |
| `Ctrl++` / `Ctrl+=` | Aumentar fonte | | `Ctrl+-` | Diminuir fonte |
| `Ctrl+0` | Fonte padrão | | `Ctrl` + roda | Zoom com mouse/touchpad |
| `Ctrl+clique` | Abrir link ou visualizar arquivo | | Clique direito | Menu contextual |
| `Ctrl+Shift+↑` / `↓` | Comando anterior / seguinte | | `Ctrl+Shift+L` | Copiar saída do último comando |
| `Ctrl+Shift+I` | Digitar em todos os painéis | | `Ctrl+Shift+S` | Conexões SSH |
| `Ctrl+Shift+R` | Renomear painel | | `F12` (global, opcional) | Terminal suspenso |
| `Ctrl+Shift+H` | Histórico de comandos | | | |

Para listar os atalhos em uso (incluindo os seus):

```bash
hacker-terminal --list-shortcuts
```

---

## 🎨 Personalização

Abra as **Preferências** com `Ctrl+,` (ou pelo ícone ⚙). Elas são organizadas em cinco abas:

| Aba | O que você ajusta |
| --- | --- |
| **Geral** | Perfil, shell personalizado, restauração de sessão, painel lateral, colagem segura e aviso de bell |
| **Aparência** | Tema (com editor), fonte, opacidade da janela, imagem de fundo e efeitos visuais |
| **Terminal** | Formato e piscar do cursor, negrito com cores claras, copiar ao selecionar, histórico e rolagem |
| **Som do teclado** | Switch, volume, som ao soltar a tecla, campo de teste e pacotes gravados |
| **Atalhos** | Todas as combinações de teclas, com gravação por tecla e restauração |

### Temas Fósforo (estilo Cool Retro Term)

<img src="docs/screenshots/phosphor-amber.png" alt="Fósforo Âmbar" width="100%">

Oito temas que imitam monitores de tubo. Como nas telas de fósforo, a paleta é **monocromática** — todas as cores do terminal são o mesmo tom em brilhos diferentes — e a seleção aparece em **vídeo inverso**.

| Tema | Fósforo | Caráter |
| --- | --- | --- |
| **Fósforo Âmbar** | âmbar `#ff8100` | O clássico monitor âmbar, com brilho quente |
| **Fósforo Verde** | verde `#0ccc68` | Monitor verde monocromático |
| **Fósforo Verde Scanlines** | verde-limão `#7cff4f` | Linhas de varredura marcadas |
| **Fósforo Vintage** | verde `#00ff3e` | Tubo envelhecido: muito ruído, cintilação e curvatura |
| **Micro 1977** | verde-água `#2fff91` | Microcomputador do fim dos anos 70 |
| **Mainframe 3270** | verde `#3cff7a` | Terminal de mainframe, nítido e discreto |
| **DOS VGA** | branco + 16 cores VGA | Monitor colorido da era DOS |
| **Fósforo Futurista** | azul `#729fcf` | Brilho azul intenso, quase sem ruído |

Para o visual completo:

1. Escolha um tema Fósforo em *Preferências → Aparência* (ou use o perfil **Retrô CRT**, que já liga tudo).
2. Ligue **Efeitos visuais** — o brilho, a curvatura, a vinheta, o ruído e a cintilação só aparecem com eles.
3. Use uma fonte de pixel. As Preferências mostram a fonte sugerida pelo tema e um botão **Usar** quando ela está instalada:

```bash
sudo apt install fonts-terminus-otb fonts-3270   # Terminus e IBM 3270
```

Todos os efeitos são ajustáveis por tema no editor (de 0 a 1) e, num tema próprio, no arquivo `.ini`:

```ini
[effects]
# brilho do fósforo, vinheta, ruído estático, cintilação e curvatura do tubo
glow = 0.55
vignette = 0.55
noise = 0.12
flicker = 0.1
curvature = 0.45
rain = false
```

> [!NOTE]
> Os efeitos são desenhados por cima do texto, sem deformá-lo: a curvatura é simulada pelos cantos do tubo e pela sombra nas bordas, não distorcendo o conteúdo como o Cool Retro Term faz com a GPU. Em troca, o custo fica em torno de 3% de CPU com o terminal parado.

### Temas modernos

<div align="center">
<img src="docs/screenshots/modern-themes.png" alt="Os seis temas modernos: Zero Day, Neon Noir, Pôr do Sol Synth, Aurora, Grafite e Névoa" width="100%">
</div>

| Tema | Estilo |
| --- | --- |
| **Zero Day** | Hacker moderno: preto profundo, verde tóxico e chuva digital discreta |
| **Neon Noir** | Noite cyberpunk em magenta e ciano, com brilho leve |
| **Pôr do Sol Synth** | Synthwave: roxo profundo com laranja e rosa |
| **Aurora** | Azul-marinho com verde-água e violeta |
| **Grafite** | Minimalista: cinzas neutros e um único azul suave |
| **Névoa (claro)** | Minimalista claro, cinza-azulado frio |

Todos os temas internos são verificados com o critério de contraste WCAG: texto e cores ANSI com pelo menos 4,5:1 sobre o fundo, texto secundário (barra de status, dicas) com 4,5:1, e a cor 8 — usada pelas sugestões do zsh e por comentários — com pelo menos 3,5:1, para continuar discreta mas legível.

### Imagem de fundo

<div align="center">
<img src="docs/screenshots/background-image.png" alt="Imagem de fundo contínua através de três painéis divididos" width="80%">
</div>

Em *Preferências → Aparência → Imagem de fundo*, escolha qualquer imagem (PNG, JPEG, WebP, SVG…) para aparecer **atrás do texto**, em todos os painéis:

- **Opacidade da imagem** (5–90%): entre 15% e 30% ela aparece sem atrapalhar a leitura.
- **Encaixe**: *Preencher* (cobre o painel, cortando as sobras), *Ajustar* (mostra a imagem inteira) ou *Lado a lado*.

A cor do tema continua por baixo e o texto, por cima; os efeitos (chuva, scanlines, visual CRT) seguem por cima de tudo. Com o painel dividido, a imagem é calculada para a aba inteira, então ela continua sem emendas através das divisões. A imagem é carregada uma vez e reaproveitada por todos os painéis.

### Temas claro e de alto contraste

- **Papel (claro)** — fundo cor de papel; todas as cores ANSI têm contraste de pelo menos 4,5:1 (WCAG AA).
- **Alto Contraste** — preto, branco e amarelo; texto com contraste de pelo menos 7:1 (WCAG AAA), e painéis inativos não são esmaecidos.

Menus e diálogos acompanham o tema: claros num tema claro, escuros num escuro.

### Temas e editor visual

Em **Aparência**, os botões fazem o seguinte:

- **Novo… / Duplicar…** — cria um tema personalizado a partir do selecionado.
- **Editar…** — abre o editor visual (só em temas personalizados; os internos nunca são alterados).
- **Remover** — apaga um tema personalizado.
- **Importar… / Exportar…** — compartilha temas como arquivos `.ini`.

O editor tem seletores de cor para toda a interface, o terminal, a seleção, o cursor, a chuva digital e as **16 cores ANSI**. Os temas ficam em `~/.config/hacker-terminal/themes/` e usam este formato:

<details>
<summary><b>Exemplo de tema (<code>matrix-green.ini</code>)</b></summary>

```ini
[theme]
# id: letras minúsculas, números e hífens
id = matrix-green
name = Matrix Green
author = Hacker Terminal

[interface]
background = #02090b
# surface: cabeçalho, painel e barra de status
surface = #080f14
foreground = #eafff8
# accent: destaques, aba ativa e botões principais
accent = #29ff9a
border = #145c48
# muted: textos secundários
muted = #477b6a
danger = #ff7383

[terminal]
background = #00090b
foreground = #72ffcb
cursor = #e8fff7
selection_background = #12664a
selection_foreground = #ffffff
# 8 cores normais + 8 claras: preto, vermelho, verde, amarelo, azul, magenta, ciano, branco
ansi = #07100f, #ff5b6e, #2de391, #e4d769, #44a8ff, #d779ff, #39d9d0, #c8e6dc, #31534a, #ff7383, #50ffad, #fff083, #72c0ff, #e69aff, #68fff4, #f0fff9

[effects]
matrix_color = #14ff8a
# entre 0 e 1
scanline_opacity = 0.12
```

Arquivos inválidos são ignorados com aviso (veja `--diagnose`) e o terminal volta com segurança ao Minimal Dark.

</details>

> [!TIP]
> A **opacidade do fundo** (30–100%) precisa de um compositor de janelas ativo (o padrão no GNOME, KDE e no XFCE com compositor ligado).

### Perfis

Um perfil guarda um conjunto completo de preferências e pode ser trocado em um clique. Há três perfis internos e você pode criar quantos quiser:

| Perfil | Tema | Destaques |
| --- | --- | --- |
| **Desenvolvimento** | Minimal Dark | Sóbrio, painel de ações visível, sem efeitos |
| **Foco** | Ice Blue | Fonte maior, sem painel lateral |
| **Retro Hacker** | Matrix Green | Chuva digital, scanlines e painel de ações visível |
| **Retrô CRT** | Fósforo Âmbar | Monitor de fósforo com brilho, curvatura e ruído, sem painel lateral |
| *Seus perfis* | qualquer um | Tema, fonte, tamanho, shell, cursor, opacidade, efeitos, painel, **diretório inicial** e **ações rápidas próprias** |

**Para criar:** ajuste tudo nas Preferências e clique em *Geral → **Salvar como perfil…***, ou use a paleta (*“Salvar configurações atuais como perfil”*). Ative **Ações rápidas próprias** para que o perfil tenha uma lista separada de ações (por exemplo, comandos do seu laboratório de testes), que troca automaticamente junto com o perfil.

```bash
hacker-terminal --list-profiles
hacker-terminal --profile pentest     # abre direto com um perfil
```

<details>
<summary><b>Formato do arquivo de perfil</b></summary>

`~/.config/hacker-terminal/profiles/pentest.ini`

```ini
[profile]
id = pentest
name = Pentest Lab
description = Laboratório autorizado
theme = matrix-green
font = JetBrainsMono Nerd Font Mono
font_size = 12
shell = zsh
cursor_shape = ibeam
opacity = 92
effects = true
sound = true
panel_visible = true
working_directory = ~/labs
# usa a lista de ações em profiles/pentest.actions
own_actions = true
```

</details>

### Som de teclado mecânico

Em **Preferências → Som do teclado**, ative o som e escolha o switch. Cada som é **sintetizado a partir dos eventos físicos** do switch — o clique da jaqueta, o *bump* tátil, a batida no fundo do curso (*bottom-out*), o retorno da haste (*top-out*) e os estabilizadores das teclas grandes.

| Switch | Caráter | O que você ouve | Amostra |
| --- | --- | --- | --- |
| 🔴 **Linear** (estilo Red) | suave | batida no fundo e retorno, sem clique | [▶ ouvir](docs/audio/switch-red.mp3) |
| 🟤 **Tátil** (estilo Brown) | discreto | um tique leve antes da batida | [▶ ouvir](docs/audio/switch-brown.mp3) |
| 🔵 **Clicky** (estilo Blue) | barulhento | clique agudo na descida **e** na subida | [▶ ouvir](docs/audio/switch-blue.mp3) |

Detalhes que deixam o som natural:

- **Descida e subida** da tecla têm sons diferentes (o retorno é mais agudo, como no real).
- **Espaço, Enter, Backspace, Shift e Tab** soam mais graves e com o chocalho dos estabilizadores.
- Cada tecla tem **variações próprias**, para não soar repetitivo.
- **Segurar uma tecla não repete o som** (o auto-repeat é silencioso, como num teclado de verdade).
- Latência total medida de **~18 ms** no PipeWire — abaixo do perceptível.

#### Som exato com gravações reais

Os sons sintetizados são aproximações. Para o som **idêntico** a um teclado real, escolha em **Switch** uma das 18 gravações que já vêm instaladas, os pacotes oficiais do [Mechvibes](https://github.com/hainguyents13/mechvibes) (MIT):

| Família | Pacotes |
| --- | --- |
| Cherry MX | Black, Blue, Brown e Red, cada um com teclas ABS e PBT |
| Full travel | MX Black, MX Blue, MX Brown, Turquoise e Full Creamy Goodness (som de descida e de subida) |
| Outros | Holy Pandas, NK Cream, Topre Purple Hybrid, EG Crystal Purple e EG Oreo |

O volume das gravações é nivelado ao carregar, para que trocar de pacote não faça o som sumir nem estourar. Elas foram compactadas por `packaging/fetch_soundpacks.py` (só os trechos de cada tecla, em mono): os 21 MB originais viraram 2,5 MB. As licenças estão em `hackerterminal/soundpacks/LICENSE`.

Para outro teclado, use **Importar pacote…** com:

1. **Um pacote do [Mechvibes](https://mechvibes.com/)**: a pasta com `config.json` (tipos `single` e `multi`, inclusive o formato 2 com variações `{0-4}` e som de subida). Cada tecla física usa o som definido para ela. Um pacote importado com o mesmo nome de um incluído tem prioridade.
2. **Uma pasta com suas próprias gravações** (WAV, OGG, MP3, FLAC ou Opus), nomeadas assim:

| Arquivo | Quando toca |
| --- | --- |
| `press.wav`, `press2.wav`, … | descida de uma tecla comum (várias = variação) |
| `release.wav`, `release2.wav`, … | subida de uma tecla comum |
| `space-press.wav`, `space-release.wav` | barra de espaço |
| `enter-press.wav`, `enter-release.wav` | Enter |
| `large-press.wav`, `large-release.wav` | Backspace, Shift, Tab, Caps Lock |

`down`/`up` também são aceitos no lugar de `press`/`release`. Os pacotes ficam em `~/.local/share/hacker-terminal/soundpacks/` (o botão **Abrir pasta** leva até lá).

### Atalhos personalizados

Em **Preferências → Atalhos**, clique em um atalho e pressione a nova combinação. `Backspace` desativa, `Esc` cancela e o botão ↺ volta ao padrão. Conflitos são avisados na hora. Também é possível editar direto no `config.ini`, usando a sintaxe do GTK:

```ini
[shortcuts]
# Ctrl+T abre uma nova aba
new_tab = <Primary>t
# ";" separa várias combinações para a mesma ação
copy = <Primary><Shift>c;<Primary>Insert
# vazio desativa o atalho
fullscreen =
```

> [!IMPORTANT]
> Nos arquivos `.ini`, escreva comentários em **linhas próprias** (começando com `#` ou `;`); um comentário no fim da linha passa a fazer parte do valor.

Identificadores disponíveis: `new_tab`, `close_pane`, `split_horizontal`, `split_vertical`, `focus_other_pane`, `next_tab`, `previous_tab`, `copy`, `paste`, `search`, `command_palette`, `toggle_panel`, `preferences`, `zoom_in`, `zoom_out`, `zoom_reset`, `fullscreen`.

### Monitor de recursos

Ligue em **Preferências → Geral → Monitor de recursos**. Fica desligado por padrão.

- **Barra de status**: um resumo como `CPU 12% · 2,4 GHz · 50 °C   RAM 3,1/7,7 GB   GPU 300 MHz`. Você escolhe os itens (CPU, clock, temperatura, RAM, GPU). Ele fica vermelho só quando a temperatura passa de 85 °C ou a memória de 90%. Clique nele para abrir os detalhes.
- **Painel lateral** (`Ctrl+Shift+B`): a seção *Sistema* mostra uso, clock e temperatura da CPU com uma barra por núcleo; memória e swap; e a GPU. Cada um tem um gráfico do último minuto.

Os dados vêm de `/proc` e `/sys` a cada 2 segundos (cerca de 2 ms por leitura), sem `sudo` e sem instalar nada. A leitura para quando a janela é minimizada ou escondida, e várias janelas compartilham a mesma leitura.

| GPU | O que aparece |
| --- | --- |
| Intel (integrada) | Clock atual e máximo. O uso em % exige permissão de administrador, e a memória de vídeo é a própria RAM, então não aparecem |
| AMD (`amdgpu`) | Uso, clock, memória de vídeo e temperatura |
| NVIDIA (driver proprietário) | Uso, clock, memória de vídeo e temperatura, pelo `nvidia-smi` |

### Ações rápidas

O painel lateral (`Ctrl+Shift+B` ou o botão ☰ no cabeçalho) traz comandos de diagnóstico local (identidade, interfaces de rede, portas, rotas, processos, SSH, saúde do sistema). Em **Editar ações…** você adiciona, edita, remove e reordena — por exemplo `make test`, `docker ps` ou `git status` — e pode exigir **confirmação** antes de ações sensíveis (marcadas com ●). Todas as ações também aparecem na paleta de comandos.

Ao clicar numa ação, **só o resultado aparece**, numa janela nas cores do tema e na fonte do terminal, que cresce com a saída (até um limite) em vez de abrir sempre do mesmo tamanho: a saída chega enquanto o comando roda, e no fim aparece ✓ ou ✗ com o código de saída e o tempo. O comando roda na pasta do painel ativo e nada é digitado no terminal. Na janela, **Parar** encerra o comando (com tudo o que ele abriu), **Copiar** copia a saída e **Rodar no terminal** digita o comando no painel, como antes. Ações que precisam de um terminal de verdade, porque pedem senha, leem o teclado ou controlam a tela (`sudo`, `vim`, `htop`, `clear`…), usam a opção **Rodar no terminal** do editor de ações; ela já vem marcada para essas ações e para *Limpar terminal*.

Uma ação pode ter **campos**: escreva `nmap -sV {alvo}` ou `ping -c {vezes=4} {host}` (`=` define um valor padrão e torna o campo opcional). Ao executar, um formulário pede os valores e mostra o comando final; os últimos valores digitados são lembrados durante a sessão. Os valores entram protegidos por aspas, então `10.0.0.5; rm -rf ~` vira um único argumento e nunca é executado. Texto entre aspas simples (`awk '{print $1}'`) e `${VAR}` não são tratados como campos. Ações com campos aparecem com “…” no painel.

---

## 🧰 Painéis, avisos e gravação

### Até 4 painéis por aba

`Ctrl+Shift+D` divide o painel ativo lado a lado e `Ctrl+Shift+E` o divide em cima e embaixo. Como cada divisão afeta só o painel ativo, dá para montar grades — por exemplo, divida lado a lado e depois divida cada metade para ter um 2×2. `Ctrl+Shift+O` percorre os painéis, `Ctrl+Shift+W` fecha o ativo (o vizinho ocupa o espaço) e a disposição completa é restaurada na próxima vez que o terminal abrir.

### Integração com o shell

Com zsh ou bash, o terminal carrega pequenos ganchos (sem mexer nos seus arquivos: o `.zshrc`/`.bashrc` continua sendo lido normalmente) que marcam cada prompt. Com isso:

- `Ctrl+Shift+↑` / `Ctrl+Shift+↓` pulam entre os comandos do histórico;
- `Ctrl+Shift+L` (ou botão direito → **Copiar saída do último comando**) copia só a saída do último comando;
- uma faixa na margem esquerda marca cada comando — na cor do tema se deu certo, **vermelha** se falhou — e a barra de status mostra `✗ SAÍDA N` após uma falha;
- o aviso de comando longo diz se o comando deu certo ou falhou, e com qual código;
- novas abas e divisões abrem na pasta atual.

Requer VTE 0.78 ou mais novo (`hacker-terminal --diagnose` informa). Desligue em *Preferências → Geral* ou com `HACKER_TERMINAL_SHELL_INTEGRATION=0`.

### Histórico de comandos

<div align="center">
<img src="docs/screenshots/history.png" alt="Diálogo do histórico de comandos com resultado, duração e pasta de cada comando; as falhas aparecem em vermelho" width="80%">
</div>

`Ctrl+Shift+H` (ou botão direito → **Histórico de comandos…**, ou a paleta) busca os comandos que você rodou **em todas as abas e janelas**, inclusive em sessões anteriores. Cada linha mostra se deu certo (✓) ou falhou (✗ e o código), quando foi, quanto durou e onde (pasta, nome do painel ou conexão SSH).

- A busca considera todas as palavras, no comando, na pasta e no lugar: `nmap 10.0.0` acha o `nmap -sV 10.0.0.5` de ontem.
- **Só falhas** mostra apenas o que deu errado; **Mostrar repetidos** lista cada execução em vez de só a mais recente.
- **Usar no terminal** (ou duplo clique/Enter) digita o comando no painel **sem apertar Enter**, para você revisar ou editar antes de rodar. **Copiar** leva para a área de transferência.

O histórico depende da integração com o shell, fica só neste computador em `~/.local/state/hacker-terminal/history.jsonl` (permissão `0600`, os 5.000 mais recentes) e pode ser desligado em *Preferências → Geral* ou apagado em **Limpar histórico…**. Como no bash e no zsh, **um comando digitado com um espaço no início não é guardado** — útil quando ele contém uma senha.

### Digitar em todos os painéis

`Ctrl+Shift+I` (ou botão direito → **Digitar em todos os painéis da aba**) envia o que você digita para todos os painéis da aba — útil para rodar o mesmo comando em vários servidores. A moldura fica vermelha e a barra de status mostra `⇉ TRANSMITINDO PARA N` enquanto estiver ligado.

### Nomes e tamanhos dos painéis

`Ctrl+Shift+R` (ou botão direito → **Renomear painel…**) dá um nome a um painel, como “servidor web” ou “logs”. O nome aparece numa faixa no topo do painel (destacada no painel ativo), na aba e nos avisos. Os nomes e o tamanho de cada divisão são restaurados junto com a sessão.

### Conexões SSH

<div align="center">
<img src="docs/screenshots/ssh.png" alt="Gerenciador de conexões SSH com conexões salvas e hosts lidos do ~/.ssh/config" width="70%">
</div>

`Ctrl+Shift+S`, o botão ⇄ na barra ou a paleta abrem o gerenciador. Os hosts do seu `~/.ssh/config` aparecem automaticamente; em **Nova…** você salva destino, porta, chave e opções extras (por exemplo `-J bastiao`). Cada conexão abre numa aba própria, com 🔒 e o nome dela, e pode ter:

- **tema próprio** — use o **Alerta Vermelho** para produção e nunca confunda as janelas;
- **confirmação antes de conectar**.

O comando é digitado no seu shell, então um erro de conexão fica visível e, ao sair do servidor, você volta ao shell local. As conexões ficam em `~/.config/hacker-terminal/ssh.ini` (permissão `0600`), sem senhas.

#### Entrar sem digitar a senha

- **Acesso por chave…** (recomendado): selecione a conexão e clique no botão. Uma aba cria sua chave SSH (se ainda não existir) e a instala no servidor; digite a senha dele uma última vez. Depois disso o login é automático, e nenhuma senha fica guardada em lugar nenhum — vale também para `scp`, `rsync` e o `ssh` do terminal comum.
- **Senha no chaveiro**: para servidores que não aceitam chave, preencha **Senha do servidor** no editor da conexão. A senha fica criptografada no chaveiro do sistema (aberto pelo seu login) e é entregue ao `ssh` por um programa auxiliar, sem aparecer na tela nem no histórico. Ela é enviada uma única vez por conexão: se o servidor recusar, a senha é pedida no terminal. Perguntas como a confirmação da impressão digital do servidor continuam aparecendo para você. Conexões com senha salva mostram 🔑; **Esquecer a senha salva** ou remover a conexão apaga a senha. Requer o pacote `gir1.2-secret-1`.

### Terminal suspenso (estilo Quake)

`hacker-terminal --dropdown` abre um terminal sem bordas no topo da tela; rodar de novo o esconde e o traz de volta, com as abas intactas. Em *Preferências → Geral → Terminal suspenso* você ajusta a altura, escolhe se ele some ao perder o foco e, no XFCE, ativa o **atalho global** (F12 por padrão) com **Ativar atalho**. O status logo acima diz se o atalho está ✓ ativo, ○ ainda não ativo ou ⚠ em uso por outro programa (que nunca é substituído); **Desativar** remove o atalho e **Testar agora** abre o terminal suspenso sem precisar da tecla. Ele se ajusta sozinho quando a resolução ou os monitores mudam. Em outros ambientes, crie um atalho que execute `hacker-terminal --dropdown`. O terminal suspenso guarda a própria sessão, separada da janela principal.

### Aviso quando um comando longo termina

Rodou uma compilação, um `nmap` ou um download e foi fazer outra coisa? Quando o comando termina numa aba que você não está olhando, a aba fica destacada e aparece uma notificação do sistema — clique nela para voltar à aba. Funciona com qualquer shell, sem configuração. Ajuste em *Preferências → Geral* (ligado por padrão, a partir de 10 segundos).

### Salvar e gravar a saída

No **botão direito** do terminal (ou na paleta):

- **Salvar saída…** grava todo o histórico atual num arquivo.
- **Gravar saída…** grava continuamente tudo o que aparecer a partir de agora, até você escolher **Parar gravação**. A aba e a barra de status mostram ● enquanto grava.

Use a extensão **`.html`** para manter as cores do tema ou **`.txt`** para texto puro. Os arquivos são criados com permissão `0600`.

> [!NOTE]
> Durante a gravação, o histórico daquele painel fica ilimitado (o VTE o guarda em arquivos temporários compactados) para que nada se perca em saídas muito rápidas. A única exceção é um comando que gera muita saída e limpa o próprio histórico ao terminar (`seq 1 3000; clear`): a saída dele pode não ser gravada.

---

## 🖼️ Visualizar imagens e planilhas

Abra imagens e planilhas **sem sair do terminal**: elas aparecem numa aba de visualização ao lado do terminal de onde vieram.

Para ver uma imagem **direto na saída**, use `ht-open --inline foto.png` (ou `-i`; `--width 40` limita a largura em colunas). A imagem é desenhada com blocos coloridos em cores reais, cabe na largura e na altura da janela e respeita a transparência, então fica certa em temas claros e escuros. Se o VTE do seu sistema tiver suporte a **sixel**, ele também é ativado (programas como `img2sixel` e `chafa -f sixel` passam a funcionar); `hacker-terminal --diagnose` diz se está disponível — no Debian/Kali o VTE vem sem sixel, e o `--inline` funciona em qualquer caso.

<div align="center">
<img src="docs/screenshots/viewer-sheet.png" alt="Planilha XLSX no visualizador" width="100%">
</div>

Há quatro jeitos de abrir:

```bash
ht-open foto.jpg relatorio.xlsx dados.csv   # um ou vários arquivos
```

- **`Ctrl+clique`** num nome de arquivo na saída do terminal — por exemplo, depois de um `ls`.
- **Botão direito** → *Visualizar arquivo…* (ou *Visualizar &lt;nome&gt;* sobre um nome de arquivo).
- **Paleta** (`Ctrl+Shift+P`) → *Visualizar imagem ou planilha…*

| Tipo | Formatos | Recursos |
| --- | --- | --- |
| 🖼️ Imagens | PNG, JPEG, GIF (animado), WebP, SVG, AVIF, TIFF, BMP, ICO e os demais do GdkPixbuf | Ajuste à janela, zoom com `+` `-` `0` `F` ou `Ctrl` + roda, orientação EXIF |
| 📊 Planilhas | CSV, TSV, XLSX/XLSM, ODS | Várias planilhas, colunas A, B, C…, datas e horas, fórmulas, copiar linhas selecionadas (`Ctrl+C`) |

Na visualização, `Esc` (ou `Ctrl+Shift+W`) fecha a aba e volta ao terminal, e o botão ⧉ abre o arquivo no aplicativo padrão do sistema.

> [!NOTE]
> Para continuar leve, o visualizador mostra até **5.000 linhas × 200 colunas** e informa o total do arquivo — exato, estimado (≈) ou mínimo (“mais de”). Arquivos de planilha acima de 200 MB e formatos antigos como `.xls` são recusados com uma mensagem; use o botão de abrir no aplicativo padrão.

<details>
<summary><b>Como funciona</b></summary>

Cada janela escuta um socket UNIX privado (permissão `0600`, dentro de um diretório `0700` do seu usuário) e informa o caminho ao shell em `HACKER_TERMINAL_SOCKET`. O `ht-open` envia apenas o caminho absoluto do arquivo; o terminal valida e abre a visualização — nenhum comando é executado. As planilhas são lidas com a biblioteca padrão do Python, em segundo plano, com limites de tamanho descompactado contra arquivos zip maliciosos.

</details>

---

## 🗂️ Referência de configuração

### Onde ficam os arquivos

| Caminho | Conteúdo |
| --- | --- |
| `~/.config/hacker-terminal/config.ini` | Preferências e atalhos |
| `~/.config/hacker-terminal/actions.ini` | Ações rápidas compartilhadas |
| `~/.config/hacker-terminal/session.json` | Abas, painéis e diretórios da última sessão |
| `~/.config/hacker-terminal/themes/` | Temas personalizados (`.ini`) |
| `~/.config/hacker-terminal/profiles/` | Perfis (`.ini`) e ações próprias (`.actions`) |
| `~/.local/share/hacker-terminal/soundpacks/` | Pacotes de som gravados |
| `~/.cache/hacker-terminal/keysounds/` | Cache dos sons sintetizados |
| `~/.local/state/hacker-terminal/hacker-terminal.log` | Log de diagnóstico (rotativo) |

Os caminhos respeitam `XDG_CONFIG_HOME`, `XDG_DATA_HOME`, `XDG_CACHE_HOME` e `XDG_STATE_HOME`. Todos os arquivos são gravados de forma **atômica** e com permissão `0600`.

<details>
<summary><b>Todas as chaves de <code>[terminal]</code> no <code>config.ini</code></b></summary>

| Chave | Valores | Padrão | Descrição |
| --- | --- | --- | --- |
| `profile` | id de perfil | `developer` | Perfil ativo |
| `theme` | id de tema | `minimal-dark` | Tema ativo |
| `font` | família | *(automática)* | Fonte; vazio escolhe a melhor Nerd Font instalada |
| `font_size` | 6–32 | `11` | Tamanho da fonte |
| `scrollback_lines` | 1000–200000 | `20000` | Linhas de histórico |
| `cursor_shape` | `block`, `ibeam`, `underline` | `block` | Formato do cursor |
| `cursor_blink` | `system`, `on`, `off` | `system` | Piscar do cursor |
| `opacity` | 30–100 | `100` | Opacidade do fundo (%) |
| `bold_is_bright` | booleano | `false` | Negrito usa a cor clara |
| `copy_on_select` | booleano | `false` | Copia ao selecionar |
| `scroll_on_output` | booleano | `false` | Rola ao receber saída |
| `scroll_on_keystroke` | booleano | `true` | Rola ao digitar |
| `shell` | comando | *(login shell)* | Ex.: `fish` ou `bash --norc` |
| `confirm_paste` | booleano | `true` | Confirma colagens perigosas |
| `bell_notify` | booleano | `true` | Marca aba/janela no bell |
| `panel_visible` | booleano | `false` | Painel de ações |
| `monitor` | booleano | `false` | Monitor de recursos na barra de status e no painel |
| `monitor_items` | lista | `cpu,freq,temp,ram,gpu` | O que o resumo da barra de status mostra |
| `restore_session` | booleano | `true` | Restaura abas ao abrir |
| `notify_commands` | booleano | `true` | Avisa quando um comando longo termina |
| `notify_after` | 3–3600 | `10` | Segundos para um comando ser considerado longo |
| `effects` | booleano | `false` | Chuva digital e scanlines |
| `sound` | booleano | `false` | Som do teclado |
| `key_switch` | `red`, `brown`, `blue`, `pack:<pasta>` | `brown` | Som do switch |
| `key_volume` | 0–100 | `70` | Volume do teclado |
| `key_release` | booleano | `true` | Som ao soltar a tecla |

Valores inválidos são normalizados para o padrão; seções desconhecidas são preservadas ao salvar.

</details>

### Variáveis de ambiente

| Variável | Efeito |
| --- | --- |
| `HACKER_TERMINAL_FONT` | Força uma família de fonte |
| `HACKER_TERMINAL_EFFECTS` / `_SOUND` | `0`, `false`, `no` ou `off` desligam o recurso |
| `HACKER_TERMINAL_AUDIO_SINK` | Força um elemento de saída do GStreamer (ex.: `pipewiresink`, `fakesink`) |

---

## 💻 Linha de comando

```text
hacker-terminal [opções] [-e COMANDO ...]
```

| Opção | Descrição |
| --- | --- |
| `-e`, `--execute COMANDO…` | Executa um comando no lugar do shell (ex.: `-e htop`) |
| `--working-directory DIR` | Diretório inicial |
| `--profile ID` / `--list-profiles` | Usa um perfil / lista os perfis |
| `--theme ID` / `--list-themes` | Usa um tema / lista os temas |
| `--font FAMÍLIA`, `--font-size N` | Fonte e tamanho só nesta janela |
| `--no-effects`, `--no-sound`, `--no-panel` | Desliga recursos nesta janela |
| `--list-shortcuts` | Lista os atalhos em uso |
| `--diagnose` | Verifica dependências, fonte, tema, perfil e atalhos |
| `--debug` | Mensagens detalhadas no terminal e no log |
| `--version` | Mostra a versão |

| `--separate` | Abre a janela num processo próprio (veja abaixo) |

Dentro do terminal também existe o comando **`ht-open ARQUIVO…`**, que abre imagens e planilhas no visualizador, e **`ht-open --inline IMAGEM`**, que desenha a imagem na própria saída.

**Um processo para todas as janelas.** Com o Hacker Terminal já aberto, `hacker-terminal` (pelo menu, atalho ou terminal) entrega a nova janela ao processo existente antes mesmo de carregar o GTK: ela abre em ~0,4 s e três janelas usam ~150 MB, em vez de ~470 MB em três processos. As preferências mudam em todas as janelas de uma vez, e só a primeira restaura a sessão salva. Opções que mudam a aparência de uma janela (`--theme`, `--profile`, `--font`, `--font-size`, `--no-effects`, `--no-sound`, `--no-panel`) abrem um processo próprio, assim como `--separate` ou a variável `HACKER_TERMINAL_SEPARATE=1`. O terminal suspenso (`--dropdown`) também tem o seu.

---

## 🔧 Como funciona

### Arquitetura

```mermaid
flowchart LR
    L["hacker_terminal.py<br/>+ launcher.py"] -->|"já aberto: entrega a janela via D-Bus"| APP
    L --> CLI["cli.py<br/>argumentos e bootstrap"] --> APP["app.py<br/>processo único, ht-open, avisos"]
    APP --> W["window/<br/>janela principal + recursos"]
    W --> D["dialogs/<br/>preferências, SSH, histórico…"]
    W --> TP["terminal.py<br/>TerminalPane (VTE + PTY)"]
    W --> ST["config · themes · profiles<br/>session · history · connections"]
    TP --> FX["effects.py<br/>chuva digital e CRT"]
    TP --> KS["keysound.py<br/>som do teclado"]
    TP --> SH(["seu shell<br/>zsh · bash · fish"])
```

A interface fica em dois pacotes. A janela (`window/`) é uma classe principal composta por *mixins*, um por recurso, para que cada arquivo tenha um assunto só:

| Módulo | Responsabilidade |
| --- | --- |
| `launcher.py` | Antes de carregar o GTK, entrega uma nova janela ao Hacker Terminal já aberto (só `Gio`, ~25 ms) |
| `cli.py`, `app.py` | Argumentos, perfil/tema e log; o `Gtk.Application` com um processo para todas as janelas, socket do `ht-open` e notificações |
| `window/main.py` | `HackerTerminal`: cabeçalho, abas, sessão, preferências, barra de status e fechamento |
| `window/panes.py`, `commands.py`, `output.py` | Divisões e transmissão; avisos, saltos e histórico de comandos; salvar/gravar saída e renomear painéis |
| `window/ssh.py`, `dropdown.py`, `viewer.py` | Abas SSH e acesso por chave; terminal suspenso; abas do visualizador |
| `window/panel.py` | Painel lateral de ações rápidas |
| `sysmon.py`, `window/monitor.py` | Leitura de CPU, memória e GPU em `/proc` e `/sys`; resumo na barra de status, seção *Sistema* do painel e gráficos |
| `dialogs/` | Preferências, editores (atalhos, temas, perfis), ações e `{campos}`, SSH, histórico, paleta e utilitários comuns |
| `terminal.py` | Painel VTE: spawn do shell, integração (marcas de prompt), pesquisa, links, colagem segura, bell, zoom |
| `themes.py` | Carrega e valida temas, gera o CSS do GTK, contraste WCAG, salva temas personalizados |
| `shortcuts.py` | Lê, valida, casa e rotula atalhos (sem depender de display) |
| `keysound.py`, `soundpacks/` | Síntese dos switches, pacotes gravados (os incluídos e os importados) e o mixer; o GStreamer só carrega quando um som toca |
| `history.py`, `connections.py`, `passwords.py` | Histórico de comandos; conexões SSH e `~/.ssh/config`; senhas no chaveiro do sistema |
| `documents.py`, `viewer.py`, `openserver.py`, `inline_image.py` | Planilhas, aba de visualização, socket do `ht-open` e imagens desenhadas na saída |
| `config.py`, `profiles.py`, `session.py`, `actions.py` | Persistência atômica de preferências, perfis, sessão e ações |
| `effects.py` | Desenha a chuva digital e o visual CRT (brilho, curvatura, vinheta, ruído) por cima do VTE |
| `dropdown.py`, `sandbox.py` | Geometria e atalho global do terminal suspenso; execução no host dentro do Flatpak |
| `fonts.py`, `project.py`, `logs.py` | Detecção de Nerd Fonts, contexto Git/venv e log rotativo |

### O terminal

Cada painel é um `Vte.Terminal` que inicia o shell de login em um PTY próprio (`$SHELL -l`, ou o shell configurado; se ele falhar, o terminal volta automaticamente ao shell padrão). Quando o shell informa o diretório atual pela sequência OSC 7 (o `vte.sh` do sistema faz isso no bash e no zsh), novas abas **herdam o diretório** e a sessão é restaurada nas pastas certas; sem OSC 7, elas abrem no diretório inicial. A barra de status lê o branch Git e o virtualenv diretamente do sistema de arquivos, sem iniciar processos.

Os efeitos retrô são desenhados **depois** do VTE, no mesmo widget — sem camadas por cima — para que cliques, toques e a rolagem do touchpad continuem chegando ao terminal.

### O motor de som

```mermaid
flowchart LR
    K["tecla pressionada"] -->|"~0,1 ms"| E["KeySoundEngine<br/>escolhe o som"]
    B[("banco de sons<br/>PCM 48 kHz em memória")] --> E
    E --> M["mixer<br/>blocos de 5 ms"]
    M -->|"appsrc"| G["GStreamer<br/>volume → pulsesink"]
    G -->|"~11 ms"| P(["PipeWire / PulseAudio"])
```

- Os sons são **pré-calculados** (ou decodificados, no caso de pacotes) para PCM 48 kHz mono e mantidos em memória, com cache em disco.
- A saída é **uma única stream contínua**: o mixer entrega um bloco de 5 ms a cada 5 ms — silêncio ou a mistura das teclas em andamento. Uma tecla nova entra no bloco seguinte, sem abrir ou reiniciar nada.
- Após 15 s sem digitar, a stream é pausada para que o dispositivo de áudio possa dormir; a retomada leva poucos milissegundos.

<details>
<summary><b>Como os switches são sintetizados</b></summary>

Cada evento físico vira um **impacto** que excita um conjunto de **modos de ressonância** (filtros de dois polos com decaimento exponencial), normalizados pelo próprio pico para que os níveis declarados sejam os níveis reais:

| Evento | Modos principais | Usado em |
| --- | --- | --- |
| Clique da jaqueta | 3,9 / 6,3 / 9,1 kHz, decaimento de 1–2,5 ms | Blue (descida e subida) |
| *Bump* tátil | 2,3 / 5,2 kHz, muito curto e fraco | Brown |
| Fundo do curso | 310 Hz – 4,7 kHz (corpo, keycap e haste) | todos |
| Retorno da haste | 760 Hz – 5,6 kHz, mais agudo | todos (subida) |
| Estabilizador | 2,1 / 3,1 / 4,7 kHz, pequenos chocalhos | Espaço, Enter, Shift, Backspace, Tab |

Teclas maiores reduzem a frequência e alongam o decaimento; pequenas variações aleatórias de tempo, frequência e amplitude evitam o efeito “metralhadora”.

</details>

---

## 🔒 Segurança e privacidade

- **Sem rede:** nenhuma telemetria, nenhum acesso externo, nenhuma dependência do PyPI.
- **Colagem segura:** textos com várias linhas ou caracteres de controle ocultos pedem confirmação antes de chegar ao shell (respeitando o *bracketed paste*).
- **Links:** só esquemas `http`, `https`, `ftp` e `file` são reconhecidos, e só abrem com ação explícita (`Ctrl+clique` ou menu).
- **Sessão:** apenas o tamanho da janela, a aba ativa e diretórios locais são salvos — nunca o conteúdo do terminal ou os processos.
- **Arquivos:** gravação atômica com permissão `0600`; pacotes de som rejeitam caminhos fora da própria pasta e links simbólicos.
- **Ações rápidas:** as ações padrão são locais e defensivas. Use ferramentas de segurança apenas em sistemas próprios ou com autorização explícita.

---

## 🩺 Solução de problemas

<details>
<summary><b>Ícones do prompt aparecem como quadrados</b></summary>

Instale uma Nerd Font (por exemplo, a JetBrainsMono Nerd Font) e confira com `hacker-terminal --diagnose`. O terminal detecta a fonte sozinho; para forçar uma, use *Preferências → Aparência → Fonte* ou `--font "JetBrainsMono Nerd Font Mono"`.

</details>

<details>
<summary><b>Não sai som do teclado</b></summary>

1. Confirme que o som está ligado em *Preferências → Som do teclado* e teste no campo de digitação.
2. Instale os plugins: `sudo apt install python3-gst-1.0 gstreamer1.0-plugins-base gstreamer1.0-plugins-good`.
3. Veja a linha de status abaixo do seletor de switch e o log em `~/.local/state/hacker-terminal/hacker-terminal.log`.
4. Se a saída padrão não for a esperada, force o elemento: `HACKER_TERMINAL_AUDIO_SINK=pipewiresink hacker-terminal`.

</details>

<details>
<summary><b>A transparência não funciona</b></summary>

A opacidade precisa de um compositor. No XFCE, ative em *Ajustes do gerenciador de janelas → Compositor*. As Preferências indicam se a transparência está disponível.

</details>

<details>
<summary><b>A rolagem do touchpad não funciona</b></summary>

Atualize para a versão 0.11.1 ou mais nova — versões anteriores bloqueavam a rolagem quando os efeitos visuais estavam ligados. Se persistir, rode com `--debug` e abra uma *issue* com o log.

</details>

<details>
<summary><b>As preferências voltaram ao padrão</b></summary>

Rode `hacker-terminal --diagnose`: ele aponta temas, perfis e atalhos inválidos. O arquivo `config.ini` é validado ao abrir; valores inválidos voltam ao padrão sem impedir a abertura.

</details>

---

## 🛠️ Desenvolvimento

```text
hacker-terminal/
├── hacker_terminal.py        # ponto de entrada
├── hackerterminal/           # código do aplicativo (módulos descritos acima)
│   └── themes/               # temas internos (.ini)
├── tests/
│   ├── test_core.py          # testes unitários (sem display)
│   ├── gui_smoke.py          # teste de integração GTK/VTE (Xvfb)
│   └── smoke.sh              # suíte completa: testes, instalação e .deb
├── packaging/                # build do .deb e metadados AppStream
├── assets/                   # ícone e arquivo .desktop
├── docs/                     # site (GitHub Pages), capturas de tela e amostras de áudio
├── install.sh · run.sh · Makefile
```

```bash
make check       # testes unitários, instalação, pacote e (com display) teste gráfico
make check-gui   # inclui o teste gráfico usando Xvfb
make run         # roda a partir do código-fonte
make deb         # gera dist/hacker-terminal_<versão>_all.deb
```

O projeto **não usa dependências do PyPI**: PyGObject, GTK, VTE e GStreamer vêm do sistema. A suíte roda o áudio em `fakesink` (sem fazer barulho), e o teste gráfico inclui eventos reais do X via `xdotool` para cobrir a rolagem. O GitHub Actions executa tudo a cada *push* e *pull request*.

### Publicar uma versão

O GitHub publica a release sozinho quando recebe uma tag `vX.Y.Z`:

1. Atualize a versão em `hackerterminal/constants.py`, `tests/smoke.sh`, no metainfo (`packaging/*.metainfo.xml`) e a seção `## X.Y.Z` do `CHANGELOG.md`.
2. Regere o site: `python3 packaging/build_site.py`. Ele também gera a demonstração interativa (`docs/demo.js`, `docs/demo.css` e os sons em `docs/audio/keys/`) a partir dos temas, perfis, ações e pacotes de som do próprio app, editados em `packaging/site/`.
3. Faça o commit e envie a tag anotada — a primeira linha da mensagem vira o título da release:

   ```bash
   git tag -a v0.19.0 -m "Hacker Terminal 0.19.0 — o que mudou"
   git push origin main v0.19.0
   ```

O fluxo [`release.yml`](.github/workflows/release.yml) confere se a tag, o `CHANGELOG.md` e o site batem com a versão, roda toda a suíte de testes, gera o `.deb` e publica a release com as notas do CHANGELOG. Se algo não bater, ele para antes de publicar. Para testar o fluxo sem publicar nada, use *Actions → release → Run workflow* com "Só testar" marcado.

Contribuições são bem-vindas — leia o [CONTRIBUTING.md](CONTRIBUTING.md). O histórico de versões está no [CHANGELOG.md](CHANGELOG.md) e as decisões técnicas e correções no [AUDIT.md](AUDIT.md).

---

## 📄 Licença

Distribuído sob a licença [MIT](LICENSE).

<div align="center">
<sub>Feito com GTK, VTE e muitas horas de terminal. ⌨️</sub>
</div>
