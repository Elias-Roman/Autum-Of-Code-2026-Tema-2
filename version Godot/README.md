# Autum of Code 2026 — Tema 2: Dungeon Knight

Proyecto de dungeon 7×7 controlado por lenguaje natural via LLM local (Ollama).  
Existen dos versiones del juego, cada una en su propio branch:

| Branch | Versión | Requisitos |
|---|---|---|
| `main` | Terminal (Python) | Python 3, Ollama |
| `godot-ui` | Interfaz gráfica (Godot 4) | Godot 4.6, Ollama |

---

## 🐍 Versión Python (`main`)

Juego de dungeon en terminal con tablero ASCII 7×7.

### Requisitos
- Python 3.10+
- [Ollama](https://ollama.com) corriendo localmente

### Instalación
```bash
pip install -r requirements.txt
ollama pull llama3
```

### Correr
```bash
python Dungeon.py
```

### Cómo jugar
El juego imprime el tablero en la terminal y espera comandos en lenguaje natural:

```
Comando: ve hacia arriba
Comando: ir al orco
Comando: abrir derecha
Comando: esperar
```

**Leyenda del tablero:**
```
K = Caballero (jugador)
O = Orco (enemigo)
C = Cofre
D = Puerta
L = Llave
. = Celda vacía
```

**Objetivo:** recoger la llave `L` y cruzar la puerta `D`.

---

## 🎮 Versión Godot 4 (`godot-ui`)

Misma lógica de juego con interfaz gráfica 2D usando assets de [Kenney Tiny Dungeon](https://kenney.nl/assets/tiny-dungeon).

### Estructura del branch
```
/
├── godot/
│   ├── project.godot
│   ├── GameState.gd       ← lógica del juego (Autoload)
│   ├── LLMBridge.gd       ← conexión HTTP a Ollama (Autoload)
│   ├── Main.gd            ← controlador de escena
│   ├── Main.tscn          ← escena principal
│   └── kenney_tiny-dungeon/
│       └── Tiles/         ← sprites individuales 16×16 px
└── README.md
```

### Requisitos
- [Godot 4.6](https://godotengine.org/download)
- [Ollama](https://ollama.com) corriendo localmente con `llama3`

### Instalación
```bash
# 1. Clonar el branch
git clone -b godot-ui https://github.com/Elias-Roman/Autum-Of-Code-2026-Tema-2.git
cd Autum-Of-Code-2026-Tema-2

# 2. Tener Ollama corriendo
ollama serve
ollama pull llama3

# 3. Abrir la carpeta /godot en Godot 4.6 y presionar F5
```

### Autoloads requeridos
En **Project → Project Settings → Autoload** deben estar registrados:

| Nombre | Ruta |
|---|---|
| `GameState` | `res://GameState.gd` |
| `LLMBridge` | `res://LLMBridge.gd` |

### Cómo jugar
Escribí comandos en lenguaje natural en el campo de texto inferior:

| Comando de ejemplo | Acción |
|---|---|
| `ve arriba` / `ir abajo` | Mover 1 celda en esa dirección |
| `ir a la izquierda` | Mover hacia la izquierda |
| `ve al orco` / `ir hacia el orco` | Acercarse al orco más cercano |
| `ir a la llave` | Moverse hacia la llave |
| `ve a la puerta` | Ir hacia la puerta |
| `abrir izquierda` | Abrir cofre en esa dirección |
| `esperar` | Pasar el turno |

**En combate:**

| Comando | Acción |
|---|---|
| `atacar` / `golpear` | Atacar al orco (1 de daño) |
| `defensa` / `guardia` | Reducir el daño recibido a la mitad |

### Reglas del juego
- El tablero es de **7×7 celdas**
- El jugador empieza con **3 HP**
- Los **cofres** bloquean el paso — usá `abrir` para interactuar
- La **puerta** bloquea sin llave — recogé la `L` primero
- Los **orcos** se mueven hacia vos cada turno y no pueden pisar objetos del mapa
- Si el HP llega a 0 → **Game Over**
- Cruzar la puerta con la llave → **¡Nivel completado!**

### Arquitectura
```
GameState.gd (Autoload)
  ├── 3 capas lógicas: board_obj (objetos) + board_fg (personajes)
  ├── Sistema de colisiones por capa
  ├── Lógica de combate por turnos
  └── Señales → Main.gd actualiza la UI

LLMBridge.gd (Autoload)
  ├── Verifica Ollama al arrancar (GET /api/tags)
  ├── POST /api/generate con prompts idénticos a Dungeon.py
  └── Parser JSON robusto con 4 intentos de extracción

Main.gd + Main.tscn
  ├── Grilla 7×7 con 4 capas visuales por celda:
  │   ColorRect (fallback) → Piso → Objeto fijo → Personaje
  ├── HUD: barra de HP, oro, estado de llave
  ├── Log de mensajes con colores (RichTextLabel)
  ├── Panel de combate integrado (no overlay)
  └── Panel de Game Over con botón Reiniciar
```

### Sprites usados (Kenney Tiny Dungeon)
| Archivo | Representa |
|---|---|
| `tile_0000.png` | Piso vacío |
| `tile_0096.png` | Caballero |
| `tile_0121.png` | Caballero muerto |
| `tile_0109.png` | Orco |
| `tile_0089.png` | Cofre cerrado |
| `tile_0091.png` | Cofre abierto |
| `tile_0045.png` | Puerta cerrada |
| `tile_0033.png` | Puerta abierta |
| `tile_0101.png` | Llave |

---

## Diferencias entre versiones

| Característica | Python (terminal) | Godot 4 (gráfico) |
|---|---|---|
| Interfaz | ASCII en terminal | Sprites 2D + UI |
| Capas visuales | 1 (texto) | 4 (piso, objeto, personaje, fallback) |
| Colisiones | Lógicas | Lógicas + feedback visual |
| Verificación Ollama | Al inicio | Al inicio + mensaje en log |
| Reinicio | Reinicia el script | Botón en pantalla |
| Combate | Texto en terminal | Panel integrado con barra de HP |

---

## Tecnologías
- [Python 3](https://python.org) — versión terminal
- [Godot 4.6](https://godotengine.org) — versión gráfica
- [Ollama](https://ollama.com) + [llama3](https://ollama.com/library/llama3) — LLM local para parsear comandos
- [Kenney Tiny Dungeon](https://kenney.nl/assets/tiny-dungeon) — assets gráficos (licencia CC0)
