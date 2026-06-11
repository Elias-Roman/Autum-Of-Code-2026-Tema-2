extends Node

# ═══════════════════════════════════════════════════════════
#  LLMBridge.gd  — Autoload singleton
#  Llama a Ollama igual que Dungeon.py
# ═══════════════════════════════════════════════════════════

const OLLAMA_URL   = "http://localhost:11434/api/generate"
const OLLAMA_MODEL = "llama3:latest"

signal respuesta_lista(data: Dictionary)
signal error_llm(msg: String)

const SYSTEM_PROMPT_MAPA = """Eres un parser de comandos para un juego de dungeons.
Convierte la instrucción del jugador a JSON válido.
Sin texto extra, sin backticks, sin markdown.

ESQUEMAS:

1) Movimiento (siempre 1 sola celda, 1 solo paso):
{"accion":"mover","pasos":[{"direccion":"arriba","cantidad":1}]}

2) Moverse hacia el objeto más cercano:
{"accion":"mover","objetivo":"cofre"}

3) Abrir cofre adyacente:
{"accion":"abrir","direccion":"derecha"}

4) Esperar:
{"accion":"esperar"}

REGLAS:
- ir/ve/muévete/camina/avanza/desplázate → "mover"
- abrir/interactuar → "abrir" si el objetivo es un cofre
- si el jugador pide abrir o usar la puerta → {"accion":"mover","objetivo":"puerta"}
- esperar/pasar/descansar → "esperar"
- Direcciones válidas: arriba, abajo, izquierda, derecha, arriba-izquierda, arriba-derecha, abajo-izquierda, abajo-derecha
- Objetivos válidos: cofre, orco, puerta, llave
- Si hay objeto destino → formato 2. Si hay dirección → formato 1.
- IMPORTANTE: el movimiento es SIEMPRE de 1 sola celda. "cantidad" siempre vale 1.
- Si el jugador pide moverse múltiples pasos o en múltiples direcciones, interpretá solo el PRIMER paso con cantidad 1.
- Si no entendés: {"accion":"desconocido"}
- Solo JSON."""

const SYSTEM_PROMPT_COMBATE = """Eres un parser de comandos de combate para un dungeon.
Convierte la instrucción a JSON válido. Sin texto extra ni backticks.

{"accion":"atacar"}
{"accion":"defensa"}
{"accion":"desconocido"}

- atacar: golpear, pegar, ataque, embisto, fight, attack
- defensa: defender, guardia, escudo, proteger, bloquear, block
- Solo JSON."""

var _http: HTTPRequest


func _ready():
	_http = HTTPRequest.new()
	add_child(_http)
	_http.request_completed.connect(_on_request_completed)


# ── Llamada pública ───────────────────────────────────────

var _modo_combate := false
var _pendiente := false

func interpretar_mapa(texto: String):
	_llamar(texto, SYSTEM_PROMPT_MAPA, false)

func interpretar_combate(texto: String):
	_llamar(texto, SYSTEM_PROMPT_COMBATE, true)

func _llamar(texto: String, system_prompt: String, combate: bool):
	if _pendiente:
		return
	_pendiente = true
	_modo_combate = combate

	GameState.llm_thinking.emit(true)

	var body = JSON.stringify({
		"model":  OLLAMA_MODEL,
		"stream": false,
		"system": system_prompt,
		"prompt": 'Instrucción: "%s"' % texto,
	})
	var headers = ["Content-Type: application/json"]
	var err = _http.request(OLLAMA_URL, headers, HTTPClient.METHOD_POST, body)
	if err != OK:
		_pendiente = false
		GameState.llm_thinking.emit(false)
		error_llm.emit("✗ No se pudo conectar a Ollama. ¿Está corriendo?\n  Inicialo con: ollama serve")


func _on_request_completed(result, response_code, _headers, body):
	_pendiente = false
	GameState.llm_thinking.emit(false)

	if result != HTTPRequest.RESULT_SUCCESS or response_code != 200:
		error_llm.emit("✗ Error HTTP %d. ¿Ollama está corriendo?" % response_code)
		return

	var text_body = body.get_string_from_utf8()
	var parsed = JSON.parse_string(text_body)
	if parsed == null:
		error_llm.emit("✗ Respuesta de Ollama no es JSON válido.")
		return

	var raw = str(parsed.get("response", ""))
	var data = _parsear_json(raw)
	respuesta_lista.emit(data)


func _parsear_json(raw: String) -> Dictionary:
	# Busca el primer {...} en el string igual que Dungeon.py
	var regex = RegEx.new()
	regex.compile(r'\{[^{}]*\}')
	var match = regex.search(raw)
	if match:
		var candidate = match.get_string()
		var data = JSON.parse_string(candidate)
		if data is Dictionary and "accion" in data:
			return data
	return {"accion": "desconocido"}
