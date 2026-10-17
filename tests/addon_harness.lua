-- A WoWLeveling addon kipróbálása a játék nélkül (lásd test_wow_addon.py).
--
--   lua addon_harness.lua <az addon mappája> <a mentett adatok fájlja>
--
-- Utánozza a játék addonoknak szóló függvényeit, lejátszik egy belépést, néhány
-- eseményt és a /wowleveling parancsot, végül úgy írja ki a WoWLevelingDB táblát,
-- ahogy a játék a SavedVariables mappába. A chatüzenetek a kimenetre kerülnek.

local addonDir, outputPath = arg[1], arg[2]

local now = 1760700000
function time()
	return now
end

local SECRET = 999.5 -- ezt a számot a játék „titkosként” adná vissza
function issecretvalue(value)
	return value == SECRET
end

UNKNOWNOBJECT = "Unknown"
SlashCmdList = {}

local timers = {}
C_Timer = {
	After = function(_, callback)
		timers[#timers + 1] = callback
	end,
}
local function RunTimers()
	local due = timers
	timers = {}
	for _, callback in ipairs(due) do
		callback()
	end
	return #due
end

-- A játékban ismeretlen esemény regisztrálása hibát okoz.
local UNKNOWN_EVENTS = { CHALLENGE_MODE_COMPLETED = true }
local frames = {}
function CreateFrame()
	local frame = { events = {} }
	function frame:RegisterEvent(event)
		if UNKNOWN_EVENTS[event] then
			error('Attempt to register unknown event "' .. event .. '"')
		end
		self.events[event] = true
	end
	function frame:SetScript(_, handler)
		self.handler = handler
	end
	frames[#frames + 1] = frame
	return frame
end
local function Fire(event, ...)
	for _, frame in ipairs(frames) do
		if frame.events[event] then
			frame.handler(frame, event, ...)
		end
	end
end

-- A belépett karakter: Zôltan, Orc Enhancement Shaman a Twisting Nether (EU) realmen.
local player = { level = 85, xp = 2900, xpMax = 10000, itemLevel = 301.5625, score = 1234 }
function UnitName()
	return "Zôltan", nil
end
function GetRealmName()
	return "Twisting Nether"
end
function GetCurrentRegion()
	return 3
end
function UnitRace()
	return "Orc", "Orc", 2
end
function UnitClass()
	return "Shaman", "SHAMAN", 7
end
function UnitLevel()
	if player.levelError then
		error("UnitLevel: próba hiba")
	end
	return player.level
end
function UnitXP()
	return player.xp
end
function UnitXPMax()
	return player.xpMax
end
function GetAverageItemLevel()
	return player.itemLevel + 1, player.itemLevel, player.itemLevel - 2
end
C_ChallengeMode = {
	GetOverallDungeonScore = function()
		return player.score
	end,
}
local SPECS = { [1] = { 262, "Elemental" }, [2] = { 263, "Enhancement" }, [3] = { 264, "Restoration" } }
player.spec = 2
C_SpecializationInfo = {
	GetSpecialization = function()
		return player.spec
	end,
	GetSpecializationInfo = function(index)
		return SPECS[index][1], SPECS[index][2], "leírás", 0, "DAMAGER", 4
	end,
}

-- Az addon betöltése, ahogy a játék: előbb a fájlja, aztán a mentett adatai.
local chunk = assert(loadfile(addonDir .. "/WoWLeveling.lua"))
chunk("WoWLeveling", {})
WoWLevelingDB = {
	version = 1,
	characters = {
		["Jaina-Draenor"] = {
			name = "Jaina",
			realm = "Draenor",
			region = "eu",
			class = "Mage",
			classFile = "MAGE",
			level = 90,
			xp = 0,
			xpMax = 0,
			itemLevel = 310.25,
			updated = 1760000000,
		},
	},
}
Fire("ADDON_LOADED", "Blizzard_Other")
Fire("ADDON_LOADED", "WoWLeveling")

-- Belépés, közben a felszerelés is változik: a két eseményre csak egyszer ment.
Fire("PLAYER_ENTERING_WORLD", true, false)
Fire("PLAYER_EQUIPMENT_CHANGED", 1, true)
print("timers: " .. RunTimers())
SlashCmdList.WOWLEVELING("")

-- Szintlépés; közben az itemlevel „titkos”, ezért a korábbi érték marad meg. A régi
-- spec-függvények is működnek, ha nincs C_SpecializationInfo.
now = now + 600
player.level, player.xp, player.xpMax, player.itemLevel = 86, 0, 12000, SECRET
C_SpecializationInfo = nil
function GetSpecialization()
	return 1
end
function GetSpecializationInfo(index)
	return SPECS[index][1], SPECS[index][2]
end
Fire("PLAYER_LEVEL_UP", 86)
Fire("PLAYER_SPECIALIZATION_CHANGED", "party1") -- más egység: nem ment
print("timers: " .. RunTimers())
Fire("PLAYER_SPECIALIZATION_CHANGED", "player")
print("timers: " .. RunTimers())

-- Egy váratlan hiba nem akasztja meg a játékot, a program jelezheti (lastError).
player.levelError = true
Fire("PLAYER_EQUIPMENT_CHANGED", 16, true)
RunTimers()
SlashCmdList.WOWLEVELING("  LISTA ")

-- Kilépés: az utolsó mentés, közben gyűlt még egy kis tapasztalat.
now = now + 60
player.levelError = nil
player.xp, player.itemLevel, player.score = 3456, 303.25, 1500.5
Fire("PLAYER_LOGOUT")

-- A mentett adatok kiírása, ahogy a játék.
local function Quote(text)
	local named = { ["\n"] = "\\n", ["\r"] = "\\r", ["\t"] = "\\t", ['"'] = '\\"', ["\\"] = "\\\\" }
	return '"' .. text:gsub('[%c"\\]', function(char)
		return named[char] or string.format("\\%03d", char:byte())
	end) .. '"'
end

local function Write(out, value, indent)
	local kind = type(value)
	if kind == "table" then
		out[#out + 1] = "{\n"
		local count = #value
		for index = 1, count do
			out[#out + 1] = indent .. "\t"
			Write(out, value[index], indent .. "\t")
			out[#out + 1] = ", -- [" .. index .. "]\n"
		end
		local keys = {}
		for key in pairs(value) do
			if type(key) ~= "number" or key < 1 or key > count or key % 1 ~= 0 then
				keys[#keys + 1] = key
			end
		end
		table.sort(keys, function(a, b)
			return tostring(a) < tostring(b)
		end)
		for _, key in ipairs(keys) do
			local name = type(key) == "string" and Quote(key) or tostring(key)
			out[#out + 1] = indent .. "\t[" .. name .. "] = "
			Write(out, value[key], indent .. "\t")
			out[#out + 1] = ",\n"
		end
		out[#out + 1] = indent .. "}"
	elseif kind == "string" then
		out[#out + 1] = Quote(value)
	elseif kind == "number" and value % 1 == 0 then
		out[#out + 1] = string.format("%d", value)
	elseif kind == "number" then
		out[#out + 1] = string.format("%.17g", value)
	else
		out[#out + 1] = tostring(value)
	end
end

local out = { "\nWoWLevelingDB = " }
Write(out, WoWLevelingDB, "")
out[#out + 1] = "\n"
local file = assert(io.open(outputPath, "wb"))
file:write(table.concat(out))
file:close()
