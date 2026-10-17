-- WoWLeveling: elmenti a karakterek adatait a WoW szintezés tervező programnak.
--
-- Minden karakterről, amellyel belépsz, elmenti a nevét, a realmjét, a régióját, a faját,
-- a kasztját, az aktív specjét, a szintjét (a tapasztalattal együtt), a felvett tárgyak
-- átlagos itemlevelét és a Mythic+ pontszámát. A játék ezeket kilépéskor,
-- kijelentkezéskor és /reload után írja ki a fiók mappájába:
--
--   World of Warcraft\_retail_\WTF\Account\<FIÓK>\SavedVariables\WoWLeveling.lua
--
-- A program (wow_leveling.py) innen olvassa be őket: indításkor magától, és a főablak
-- „Importálás most” gombjával.
--
-- Parancsok: /wowleveling (vagy /wowlvl): a karakter elmentett adatai;
--            /wowleveling lista: az összes elmentett karakter.

local ADDON_NAME = ...
local DB_VERSION = 1
local PREFIX = "|cff33ff99WoWLeveling:|r "
-- A GetCurrentRegion() értékei: 1 = US, 2 = KR, 3 = EU, 4 = TW, 5 = CN.
local REGIONS = { "us", "kr", "eu", "tw", "cn" }

-- A Midnight óta egyes adatok titkosak (secret value) lehetnek: ezekkel nem lehet
-- számolni, és nem menthetők, ezért ilyenkor az érték üres marad.
local isSecret = issecretvalue or function()
	return false
end

local function Plain(value)
	if value == nil or isSecret(value) then
		return nil
	end
	return value
end

local function Region()
	local id = GetCurrentRegion and Plain(GetCurrentRegion())
	if id and REGIONS[id] then
		return REGIONS[id]
	end
	local name = GetCurrentRegionName and Plain(GetCurrentRegionName())
	if type(name) == "string" and name ~= "" then
		return name:lower()
	end
	return nil
end

-- Az aktív spec azonosítója és neve. A 11.2-es patch óta a C_SpecializationInfo
-- függvényei az újak; a régiek csak a régi addonok kedvéért maradtak meg.
local function CurrentSpec()
	local api = C_SpecializationInfo
	local getIndex = api and api.GetSpecialization or GetSpecialization
	local getInfo = api and api.GetSpecializationInfo or GetSpecializationInfo
	if not getIndex or not getInfo then
		return nil, nil
	end
	local index = Plain(getIndex())
	if not index then
		return nil, nil
	end
	local specID, specName = getInfo(index)
	return Plain(specID), Plain(specName)
end

-- A felvett tárgyak átlagos itemlevele, ahogy a karakterlap mutatja (kerekítés nélkül).
local function EquippedItemLevel()
	if not GetAverageItemLevel then
		return nil
	end
	local _, equipped = GetAverageItemLevel()
	equipped = Plain(equipped)
	if type(equipped) == "number" and equipped > 0 then
		return equipped
	end
	return nil
end

-- Az aktuális szezon Mythic+ pontszáma.
local function MythicPlusScore()
	local api = C_ChallengeMode
	if not api or not api.GetOverallDungeonScore then
		return nil
	end
	local score = Plain(api.GetOverallDungeonScore())
	if type(score) == "number" and score >= 0 then
		return score
	end
	return nil
end

local function InitDB()
	if type(WoWLevelingDB) ~= "table" then
		WoWLevelingDB = {}
	end
	if type(WoWLevelingDB.characters) ~= "table" then
		WoWLevelingDB.characters = {}
	end
	WoWLevelingDB.version = DB_VERSION
end

-- A belépett karakter adatainak mentése. Visszaadja a karakter elmentett adatait
-- (nil, ha még nem ismert, pl. belépés közben).
local function Snapshot()
	if type(WoWLevelingDB) ~= "table" then
		return nil
	end
	local name = Plain(UnitName("player"))
	local realm = Plain(GetRealmName())
	if type(name) ~= "string" or name == "" or name == UNKNOWNOBJECT or type(realm) ~= "string" or realm == "" then
		return nil
	end
	local raceName, raceFile, raceID = UnitRace("player")
	local className, classFile, classID = UnitClass("player")
	local specID, specName = CurrentSpec()
	local fresh = {
		name = name,
		realm = realm,
		region = Region(),
		race = Plain(raceName),
		raceFile = Plain(raceFile),
		raceID = Plain(raceID),
		class = Plain(className),
		classFile = Plain(classFile),
		classID = Plain(classID),
		specID = specID,
		spec = specName,
		level = Plain(UnitLevel("player")),
		xp = Plain(UnitXP("player")),
		xpMax = Plain(UnitXPMax("player")),
		itemLevel = EquippedItemLevel(),
		mythicPlusScore = MythicPlusScore(),
		updated = time(),
	}
	local key = name .. "-" .. realm
	local entry = WoWLevelingDB.characters[key]
	if type(entry) ~= "table" then
		entry = {}
		WoWLevelingDB.characters[key] = entry
	end
	for field, value in pairs(fresh) do -- ami most nem ismert, az a korábbi értéken marad
		entry[field] = value
	end
	WoWLevelingDB.lastError = nil
	return entry
end

local saveScheduled = false

-- Mentés; egy váratlan hiba ne zavarja a játékot, csak a program jelezze (lastError).
local function Save()
	saveScheduled = false
	local ok, result = pcall(Snapshot)
	if ok then
		return result
	end
	if type(WoWLevelingDB) == "table" then
		WoWLevelingDB.lastError = tostring(result)
	end
	return nil
end

-- Több gyors egymás utáni esemény (pl. a felszerelés cseréje) után csak egyszer ment.
local function SaveSoon(delay)
	if saveScheduled then
		return
	end
	if C_Timer and C_Timer.After then
		saveScheduled = true
		C_Timer.After(delay, Save)
	else
		Save()
	end
end

local function Number(value, digits)
	return (string.format("%." .. digits .. "f", value):gsub("%.", ","))
end

local function Describe(entry)
	local parts = {}
	if type(entry.level) == "number" then
		local level = entry.level
		if type(entry.xp) == "number" and type(entry.xpMax) == "number" and entry.xpMax > 0 then
			level = level + math.min(math.floor(entry.xp * 100 / entry.xpMax), 99) / 100
		end
		parts[#parts + 1] = "szint " .. Number(level, 2)
	end
	if type(entry.itemLevel) == "number" then
		parts[#parts + 1] = "itemlevel " .. Number(entry.itemLevel, 2)
	end
	if type(entry.mythicPlusScore) == "number" and entry.mythicPlusScore > 0 then
		parts[#parts + 1] = "M+ pontszám " .. Number(entry.mythicPlusScore, 0)
	end
	local text = tostring(entry.name) .. " (" .. tostring(entry.realm) .. ")"
	if #parts > 0 then
		text = text .. ": " .. table.concat(parts, ", ")
	end
	return text
end

local function Print(text)
	print(PREFIX .. text)
end

SLASH_WOWLEVELING1 = "/wowleveling"
SLASH_WOWLEVELING2 = "/wowlvl"
SlashCmdList.WOWLEVELING = function(message)
	InitDB()
	local current = Save()
	local command = (message or ""):match("^%s*(.-)%s*$"):lower()
	if command == "lista" or command == "list" then
		local keys = {}
		for key, entry in pairs(WoWLevelingDB.characters) do
			if type(entry) == "table" then
				keys[#keys + 1] = key
			end
		end
		table.sort(keys)
		Print(#keys .. " karakter adatai vannak elmentve:")
		for _, key in ipairs(keys) do
			print("  " .. Describe(WoWLevelingDB.characters[key]))
		end
	elseif current then
		Print(Describe(current))
	else
		Print("most nem sikerült elmenteni a karakter adatait.")
	end
	if WoWLevelingDB.lastError then
		Print("hiba: " .. WoWLevelingDB.lastError)
	end
	Print("A program a kilépés, a kijelentkezés vagy a /reload után látja az új adatokat.")
end

local frame = CreateFrame("Frame")
frame:SetScript("OnEvent", function(_, event, arg1)
	if event == "ADDON_LOADED" then
		if arg1 == ADDON_NAME then
			InitDB()
		end
	elseif event == "PLAYER_LOGOUT" then
		Save() -- az utolsó esemény, mielőtt a játék kiírja a mentett adatokat
	elseif event == "PLAYER_SPECIALIZATION_CHANGED" then
		if arg1 == nil or arg1 == "player" then
			SaveSoon(1)
		end
	elseif event == "CHALLENGE_MODE_COMPLETED" then
		SaveSoon(5) -- a Mythic+ pontszám kicsit később frissül
	else
		SaveSoon(2)
	end
end)

for _, event in ipairs({
	"ADDON_LOADED",
	"PLAYER_ENTERING_WORLD",
	"PLAYER_LEVEL_UP",
	"PLAYER_EQUIPMENT_CHANGED",
	"PLAYER_SPECIALIZATION_CHANGED",
	"CHALLENGE_MODE_COMPLETED",
	"PLAYER_LOGOUT",
}) do
	pcall(frame.RegisterEvent, frame, event) -- egy esetleg megszűnt esemény se okozzon hibát
end
