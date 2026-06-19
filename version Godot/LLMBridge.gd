extends Node

# ═══════════════════════════════════════════════════════════
#  LLMBridge.gd  v3  — Godot 4.6
#  - Prompts compactos y salida JSON estructurada
#  - Parser regex con re.DOTALL equivalente ([\s\S]*?)
#  - Verificación de Ollama al inicio con lista de modelos
#  - Señal ollama_status para mostrar info en el log
# ═══════════════════════════════════════════════════════════

const OLLAMA_URL    = "http://127.0.0.1:11434/api/generate"
const OLLAMA_TAGS   = "http://127.0.0.1:11434/api/tags"
const OLLAMA_MODEL  = "llama3:latest"
const OLLAMA_KEEP_ALIVE  = "30m"
const OLLAMA_NUM_CTX     = 512
const OLLAMA_NUM_PREDICT = 40
const CACHE_MAX          = 64

signal respuesta_lista(data: Dictionary)
signal error_llm(msg: String)
signal ollama_status(ok: bool, info: String)

# ── Prompts compactos: menos tokens de entrada y salida ──────────
const SYSTEM_PROMPT_MAPA = \
"""Clasifica una orden para un dungeon y responde solo JSON.

Salidas:
- Mover en dirección: {"accion":"mover","direccion":"arriba"}
- Ir hacia cofre/orco/puerta/llave: {"accion":"mover","objetivo":"orco"}
- Abrir o interactuar con un cofre: {"accion":"abrir","direccion":"derecha"}
- Esperar o descansar: {"accion":"esperar"}
- No entendida: {"accion":"desconocido"}

Reglas:
- Direcciones: arriba, abajo, izquierda, derecha, arriba-izquierda, arriba-derecha, abajo-izquierda, abajo-derecha.
- Si se menciona un objeto como destino, usa objetivo aunque diga "hacia".
- "abrir/usar puerta" significa mover hacia objetivo puerta.
- Para abrir un cofre usa la dirección indicada.
- Ignora cantidades y direcciones posteriores: ejecuta solo el primer paso."""

const SYSTEM_PROMPT_COMBATE = \
"""Clasifica una orden de combate y responde solo JSON.
Ataque (atacar, golpear, pegar, embestir, fight, attack): {"accion":"atacar"}
Defensa (defender, guardia, escudo, proteger, bloquear, block): {"accion":"defensa"}
Otra cosa: {"accion":"desconocido"}"""

const FORMAT_MAPA = {
	"type": "object",
	"properties": {
		"accion": {"type": "string", "enum": ["mover", "abrir", "esperar", "desconocido"]},
		"direccion": {"type": "string", "enum": ["arriba", "abajo", "izquierda", "derecha", "arriba-izquierda", "arriba-derecha", "abajo-izquierda", "abajo-derecha"]},
		"objetivo": {"type": "string", "enum": ["cofre", "orco", "puerta", "llave"]},
	},
	"required": ["accion"],
	"additionalProperties": false,
}

const FORMAT_COMBATE = {
	"type": "object",
	"properties": {
		"accion": {"type": "string", "enum": ["atacar", "defensa", "desconocido"]},
	},
	"required": ["accion"],
	"additionalProperties": false,
}

var _http_game   : HTTPRequest   # para llamadas al LLM
var _http_check  : HTTPRequest   # para verificar Ollama al inicio
var _http_warmup : HTTPRequest   # para cargar el modelo antes del primer comando

var _pendiente   : bool = false
var _combate     : bool = false
var _clave_pendiente := ""
var _inicio_ms := 0
var _cache: Dictionary = {}
var _cache_order: Array[String] = []


func _ready():
	_http_game = HTTPRequest.new()
	add_child(_http_game)
	_http_game.request_completed.connect(_on_game_done)

	_http_check = HTTPRequest.new()
	add_child(_http_check)
	_http_check.request_completed.connect(_on_check_done)

	_http_warmup = HTTPRequest.new()
	add_child(_http_warmup)
	_http_warmup.request_completed.connect(_on_warmup_done)

	# Verificar Ollama al arrancar (igual que verificar_modelo() en Dungeon.py)
	_verificar_ollama()


# ═══════════════════════════════════════════════════════════
#  VERIFICACIÓN DE OLLAMA AL INICIO
# ═══════════════════════════════════════════════════════════

func _verificar_ollama():
	var err = _http_check.request(OLLAMA_TAGS, [], HTTPClient.METHOD_GET)
	if err != OK:
		ollama_status.emit(false, "✗ No se pudo conectar a Ollama. ¿Está corriendo?\n  Inicialo con: ollama serve")


func _on_check_done(result, code, _headers, body):
	if result != HTTPRequest.RESULT_SUCCESS or code != 200:
		ollama_status.emit(false, "✗ Ollama no responde (HTTP %d). Inicialo con: ollama serve" % code)
		return

	var parsed = JSON.parse_string(body.get_string_from_utf8())
	if parsed == null:
		ollama_status.emit(false, "✗ Ollama respondió con formato inesperado.")
		return

	var modelos : Array = parsed.get("models", [])
	var nombres : Array = []
	for m in modelos:
		var nombre = str(m.get("name", ""))
		if nombre != "":
			nombres.append(nombre)

	var base = OLLAMA_MODEL.split(":")[0]
	var encontrado = false
	for n in nombres:
		if n.split(":")[0] == base:
			encontrado = true
			break

	if not encontrado:
		var lista = ", ".join(nombres) if nombres.size() > 0 else "(ninguno)"
		ollama_status.emit(false,
			"✗ Modelo '%s' no instalado.\n  Disponibles: %s\n  Instalalo con: ollama pull %s" \
			% [OLLAMA_MODEL, lista, OLLAMA_MODEL])
	else:
		ollama_status.emit(true,
			"Ollama conectado · precargando modelo: %s  |  otros: %s" \
			% [OLLAMA_MODEL, ", ".join(nombres) if nombres.size() > 1 else "(solo este)"])
		_precalentar_modelo()


func _precalentar_modelo():
	var body = JSON.stringify({
		"model": OLLAMA_MODEL,
		"stream": false,
		"keep_alive": OLLAMA_KEEP_ALIVE,
		"options": {
			"num_ctx": OLLAMA_NUM_CTX,
		},
	})
	_http_warmup.request(
		OLLAMA_URL,
		["Content-Type: application/json"],
		HTTPClient.METHOD_POST,
		body
	)


func _on_warmup_done(result, code, _headers, _body):
	if result == HTTPRequest.RESULT_SUCCESS and code == 200:
		ollama_status.emit(true, "✓ %s precargado y listo para responder." % OLLAMA_MODEL)


# ═══════════════════════════════════════════════════════════
#  LLAMADAS AL LLM
# ═══════════════════════════════════════════════════════════

func interpretar_mapa(texto: String):
	_interpretar(texto, SYSTEM_PROMPT_MAPA, false)

func interpretar_combate(texto: String):
	_interpretar(texto, SYSTEM_PROMPT_COMBATE, true)

func _interpretar(texto: String, prompt: String, combate: bool):
	var clave = _crear_clave_cache(texto, combate)
	if clave in _cache:
		print("LLM cache: 0 ms")
		respuesta_lista.emit(_cache[clave].duplicate(true))
		return
	_llamar(texto, prompt, combate, clave)

func _llamar(texto: String, prompt: String, combate: bool, clave: String):
	if _pendiente:
		return
	_pendiente = true
	_combate   = combate
	_clave_pendiente = clave
	_inicio_ms = Time.get_ticks_msec()
	GameState.notify_thinking(true)

	var body = JSON.stringify({
		"model":  OLLAMA_MODEL,
		"stream": false,
		"format": FORMAT_COMBATE if combate else FORMAT_MAPA,
		"keep_alive": OLLAMA_KEEP_ALIVE,
		"system": prompt,
		"prompt": 'Orden: "%s"' % texto,
		"options": {
			"temperature": 0.0,
			"num_ctx": OLLAMA_NUM_CTX,
			"num_predict": OLLAMA_NUM_PREDICT,
		},
	})
	var err = _http_game.request(
		OLLAMA_URL,
		["Content-Type: application/json"],
		HTTPClient.METHOD_POST,
		body
	)
	if err != OK:
		_pendiente = false
		GameState.notify_thinking(false)
		error_llm.emit("✗ No se pudo conectar a Ollama (puerto 11434).")


func _on_game_done(result, code, _headers, body):
	_pendiente = false
	GameState.notify_thinking(false)
	print("LLM %s: %d ms" % [OLLAMA_MODEL, Time.get_ticks_msec() - _inicio_ms])

	if result != HTTPRequest.RESULT_SUCCESS or code != 200:
		error_llm.emit("✗ Error HTTP %d — ¿Ollama sigue corriendo?" % code)
		return

	var parsed = JSON.parse_string(body.get_string_from_utf8())
	if parsed == null:
		error_llm.emit("✗ Ollama devolvió una respuesta no parseable.")
		return

	var raw  : String     = str(parsed.get("response", ""))
	var data : Dictionary = _normalizar_respuesta(_parsear_json(raw))
	if _respuesta_cacheable(data):
		_guardar_cache(_clave_pendiente, data)
	respuesta_lista.emit(data)


func _normalizar_respuesta(data: Dictionary) -> Dictionary:
	if data.get("accion", "") == "mover" and "direccion" in data:
		return {
			"accion": "mover",
			"pasos": [{"direccion": data["direccion"], "cantidad": 1}],
		}
	return data


func _crear_clave_cache(texto: String, combate: bool) -> String:
	var palabras = texto.strip_edges().to_lower().split(" ", false)
	return ("combate:" if combate else "mapa:") + " ".join(palabras)


func _respuesta_cacheable(data: Dictionary) -> bool:
	match data.get("accion", ""):
		"mover": return "objetivo" in data or "pasos" in data
		"abrir": return "direccion" in data
		"esperar", "atacar", "defensa": return true
		_: return false


func _guardar_cache(clave: String, data: Dictionary):
	if clave in _cache:
		return
	if _cache_order.size() >= CACHE_MAX:
		_cache.erase(_cache_order.pop_front())
	_cache[clave] = data.duplicate(true)
	_cache_order.append(clave)


# ═══════════════════════════════════════════════════════════
#  PARSER JSON  (equivalente a _parsear_json_con_estado en Dungeon.py)
#  Usa [\s\S]*? para capturar JSONs multilinea, igual que re.DOTALL
# ═══════════════════════════════════════════════════════════

func _parsear_json(raw: String) -> Dictionary:
	# Intento 1: parsear el string completo directamente
	var direct = JSON.parse_string(raw.strip_edges())
	if direct is Dictionary and "accion" in direct:
		return direct

	# Intento 2: regex greedy que captura el PRIMER { ... } incluyendo saltos de línea
	# equivalente a re.search(r'\{.*\}', raw, re.DOTALL) de Python
	var re = RegEx.new()
	re.compile(r'\{[\s\S]*?\}')   # non-greedy, multilinea
	var matches = re.search_all(raw)
	for m in matches:
		var candidate = m.get_string()
		var d = JSON.parse_string(candidate)
		if d is Dictionary and "accion" in d:
			return d

	# Intento 3: regex greedy para JSONs más largos con texto dentro
	var re2 = RegEx.new()
	re2.compile(r'\{[\s\S]*\}')
	var m2 = re2.search(raw)
	if m2:
		var d2 = JSON.parse_string(m2.get_string())
		if d2 is Dictionary and "accion" in d2:
			return d2

	# Intento 4: buscar manualmente las palabras clave del JSON esperado
	# (fallback para cuando el LLM devuelve texto con el JSON embebido)
	var lower = raw.to_lower()
	if '"accion"' in lower or "'accion'" in lower:
		# Buscar desde el primer { hasta el último }
		var start = raw.find("{")
		var end   = raw.rfind("}")
		if start != -1 and end != -1 and end > start:
			var d3 = JSON.parse_string(raw.substr(start, end - start + 1))
			if d3 is Dictionary and "accion" in d3:
				return d3

	return {"accion": "desconocido"}
