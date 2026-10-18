-- WoWLeveling: elmenti a karakterek adatait a WoW szintezés tervező programnak.
--
-- Minden karakterről, amellyel belépsz, elmenti a nevét, a realmjét, a régióját, a faját,
-- a kasztját, az aktív specjét, a szintjét két tizedesre (a tapasztalattal együtt, pl. 85.29),
-- a felvett tárgyak átlagos itemlevelét és a Mythic+ pontszámát. A játék ezeket kilépéskor,
-- kijelentkezéskor és /reload után írja ki a fiók mappájába:
--
--   World of Warcraft\_retail_\WTF\Account\<FIÓK>\SavedVariables\WoWLeveling.lua
--
-- A program (wow_leveling.py) innen olvassa be őket: indításkor magától, és a főablak
-- „Importálás most” gombjával.
--
-- Egy kis ablakban azt is mutatja, melyik karakter van a legnagyobb lemaradásban szintben,
-- itemlevelben és Mythic+ pontszámban (a program terve szerint, amelyet a program a
-- PlanData.lua fájlba szinkronizál; a számolás a Plan.lua-ban van). Ha a három karakter
-- valamelyikével játszol, az ablak a játékbeli adatokból magától frissül.
--
-- Parancsok: /wowleveling (vagy /wowlvl): a karakter elmentett adatai;
--            /wowleveling lista: az összes elmentett karakter;
--            /wowleveling ablak: a lemaradás ablakának be- és kikapcsolása.

local ADDON_NAME, ns = ...
local Plan = ns.Plan
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

-- Szint századokban, a tapasztalattal együtt: 85-ös szint, a következőhöz szükséges tapasztalat
-- 29,99%-a -> 8529 (a százalék lefelé kerekítve, mint a programban). A már két tizedesre mentett
-- szintet (85.29) változatlanul hagyja.
local function LevelValue(level, xp, xpMax)
	if type(level) ~= "number" or level < 1 then
		return nil
	end
	if level % 1 ~= 0 then
		return math.floor(level * 100 + 0.5)
	end
	local value = level * 100
	if type(xp) == "number" and type(xpMax) == "number" and xpMax > 0 and xp > 0 then
		value = value + math.min(math.floor(xp * 100 / xpMax), 99)
	end
	return value
end

local function InitDB()
	if type(WoWLevelingDB) ~= "table" then
		WoWLevelingDB = {}
	end
	if type(WoWLevelingDB.characters) ~= "table" then
		WoWLevelingDB.characters = {}
	end
	if type(WoWLevelingDB.window) ~= "table" then
		WoWLevelingDB.window = {}
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
	local xp, xpMax = Plain(UnitXP("player")), Plain(UnitXPMax("player"))
	local level = LevelValue(Plain(UnitLevel("player")), xp, xpMax)
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
		level = level and level / 100, -- két tizedesre, a tapasztalattal együtt (pl. 85.29)
		xp = xp,
		xpMax = xpMax,
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
	local level = LevelValue(entry.level, entry.xp, entry.xpMax)
	if level then
		parts[#parts + 1] = "szint " .. Number(level / 100, 2)
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

-- === A lemaradás ablaka ===

local WIDTH, HEIGHT = 370, 122 -- a lábléc két sorba is kifér
local ROWS = { -- az ablak sorai: a Plan.Compute eredményének kulcsa, felirat, a számok léptéke
	{ key = "level", label = "Szint", scale = 100, digits = 2 },
	{ key = "itemLevel", label = "Itemlevel", scale = 100, digits = 2 },
	{ key = "score", label = "Mythic+", scale = 10, digits = 1 },
}
local COLUMNS = { 10, 78, 190, 280 } -- felirat, karakter, cél, hiány
local window
local tracking = false -- a kilistázott karakterek egyikével játszik: az ablak magától frissül
local refreshScheduled = false
local shownDay -- az ablakban mutatott nap (éjfél után újraszámol)

local function Today()
	local now = date("*t")
	return Plan.DayNumber(now.year, now.month, now.day)
end

local function RealmKey(realm)
	return (tostring(realm or ""):lower():gsub("[^%w]", ""))
end

-- Ugyanaz a karakter-e (a terv karakterének realm nélkül elég a neve).
local function SameCharacter(source, name, realm)
	if tostring(source.name or ""):lower() ~= tostring(name or ""):lower() then
		return false
	end
	local sourceRealm = RealmKey(source.realm)
	return sourceRealm == "" or sourceRealm == RealmKey(realm)
end

local function IsPlayer(source)
	return SameCharacter(source, Plain(UnitName("player")), Plain(GetRealmName()))
end

local function ItemLevelValue(itemLevel) -- századokban
	if type(itemLevel) == "number" and itemLevel > 0 then
		return math.floor(itemLevel * 100 + 0.5)
	end
	return nil
end

local function ScoreValue(score) -- tizedre kerekítve, századokban (mint a program)
	if type(score) == "number" and score > 0 then
		return math.floor(score * 10 + 0.5) * 10
	end
	return nil
end

-- Az addon mentése a terv egy karakteréről (nil, ha nincs, vagy nem egyértelmű).
local function FindSnapshot(source)
	local found
	for _, entry in pairs(WoWLevelingDB.characters) do
		if type(entry) == "table" and SameCharacter(source, entry.name, entry.realm) then
			if found then
				return nil
			end
			found = entry
		end
	end
	return found
end

-- A program adatánál frissebb értékek: az addon újabb mentése (amit a program még nem olvasott
-- be), és a most játszott karakter élő adatai.
local function Override(source)
	local level, itemLevel, score
	local entry = FindSnapshot(source)
	if entry and (tonumber(entry.updated) or 0) > (tonumber(source.addonUpdated) or 0) then
		level = LevelValue(entry.level, entry.xp, entry.xpMax)
		itemLevel = ItemLevelValue(entry.itemLevel)
		score = ScoreValue(entry.mythicPlusScore)
	end
	if IsPlayer(source) then
		level = LevelValue(Plain(UnitLevel("player")), Plain(UnitXP("player")), Plain(UnitXPMax("player"))) or level
		itemLevel = ItemLevelValue(EquippedItemLevel()) or itemLevel
		score = ScoreValue(MythicPlusScore()) or score
	end
	return level, itemLevel, score
end

local function ColoredName(char)
	local colors = RAID_CLASS_COLORS and char.class and RAID_CLASS_COLORS[char.class]
	if colors and colors.colorStr then
		return "|c" .. colors.colorStr .. char.name .. "|r"
	end
	return char.name
end

local function GoalDayText(goalDay, today)
	if goalDay == today then
		return nil
	end
	if goalDay == today + 1 then
		return "a szint a holnapi cél"
	end
	return "a szint a " .. (goalDay - today) .. " nap múlva esedékes cél"
end

local function SetRow(cells, name, target, missing)
	cells[2]:SetText(name or "")
	cells[3]:SetText(target or "")
	cells[4]:SetText(missing or "")
end

local function Refresh()
	local data = WoWLevelingPlanData
	local today = Today()
	shownDay = today
	if type(data) ~= "table" then
		for index, row in ipairs(ROWS) do
			local note = index == 1 and "Még nincs szinkronizált terv."
				or index == 2 and "A programban: Szinkronizálás, majd /reload."
				or nil
			SetRow(window.rows[row.key], note and ("|cff999999" .. note .. "|r"))
		end
		window.footer:SetText("")
		return
	end
	local result = Plan.Compute(data, Plan.Characters(data, Override), today)
	local live
	for _, row in ipairs(ROWS) do
		local cells, line = window.rows[row.key], result[row.key]
		if line.char then
			if IsPlayer(line.char.source) then
				tracking, live = true, line.char.name
			end
			SetRow(
				cells,
				ColoredName(line.char),
				"cél: " .. Number(line.target / row.scale, row.digits),
				"|cffff6060hiányzik: " .. Number(line.missing / row.scale, row.digits) .. "|r"
			)
		elseif line.ok then
			SetRow(cells, "|cff60ff60senki sincs lemaradásban|r")
		else
			SetRow(cells, "|cff999999" .. tostring(line.problem) .. "|r")
		end
	end
	local parts = { "Szinkronizálva: " .. date("%Y-%m-%d %H:%M", tonumber(data.generated) or 0) }
	parts[#parts + 1] = GoalDayText(result.goalDay, today)
	if live then
		parts[#parts + 1] = "automatikus frissítés: " .. live
	end
	window.footer:SetText(table.concat(parts, " · "))
end

-- Az ablak újraszámolása; egy váratlan hiba csak az ablakban látszik, a játékot nem zavarja.
local function RefreshWindow()
	refreshScheduled = false
	tracking = false
	if not window or not window:IsShown() then
		return
	end
	local ok, problem = pcall(Refresh)
	if not ok then
		tracking = false
		window.footer:SetText("|cffff6060hiba: " .. tostring(problem) .. "|r")
	end
end

-- Több gyors egymás utáni esemény után csak egyszer számol.
local function RefreshSoon()
	if refreshScheduled then
		return
	end
	if C_Timer and C_Timer.After then
		refreshScheduled = true
		C_Timer.After(1, RefreshWindow)
	else
		RefreshWindow()
	end
end

local function SavePosition(frame)
	local point, _, relativePoint, x, y = frame:GetPoint()
	local settings = WoWLevelingDB.window
	settings.point, settings.relativePoint, settings.x, settings.y = point, relativePoint, x, y
end

local function CreateWindow()
	local frame = CreateFrame("Frame", "WoWLevelingWindow", UIParent, BackdropTemplateMixin and "BackdropTemplate" or nil)
	frame:SetSize(WIDTH, HEIGHT)
	frame:SetFrameStrata("MEDIUM")
	frame:SetClampedToScreen(true)
	frame:SetMovable(true)
	frame:EnableMouse(true)
	frame:RegisterForDrag("LeftButton")
	frame:SetScript("OnDragStart", frame.StartMoving)
	frame:SetScript("OnDragStop", function(self)
		self:StopMovingOrSizing()
		SavePosition(self)
	end)
	if frame.SetBackdrop then
		frame:SetBackdrop({
			bgFile = "Interface\\Tooltips\\UI-Tooltip-Background",
			edgeFile = "Interface\\Tooltips\\UI-Tooltip-Border",
			tile = true,
			tileSize = 16,
			edgeSize = 16,
			insets = { left = 4, right = 4, top = 4, bottom = 4 },
		})
		frame:SetBackdropColor(0, 0, 0, 0.75)
	end
	local settings = WoWLevelingDB.window
	frame:SetPoint(settings.point or "CENTER", UIParent, settings.relativePoint or "CENTER", settings.x or 0, settings.y or 220)

	local title = frame:CreateFontString(nil, "OVERLAY", "GameFontNormal")
	title:SetPoint("TOPLEFT", COLUMNS[1], -9)
	title:SetText("WoWLeveling - a legnagyobb lemaradás")
	local close = CreateFrame("Button", nil, frame, "UIPanelCloseButton")
	close:SetPoint("TOPRIGHT", 0, 0)
	close:SetScript("OnClick", function()
		ns.ShowWindow(false)
	end)

	frame.rows = {}
	for index, row in ipairs(ROWS) do
		local cells = {}
		for column, x in ipairs(COLUMNS) do
			local cell = frame:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
			cell:SetPoint("TOPLEFT", x, -14 - index * 17)
			cell:SetJustifyH("LEFT")
			cells[column] = cell
		end
		cells[1]:SetText(row.label)
		frame.rows[row.key] = cells
	end
	frame.footer = frame:CreateFontString(nil, "OVERLAY", "GameFontDisableSmall")
	frame.footer:SetPoint("BOTTOMLEFT", COLUMNS[1], 9)
	frame.footer:SetWidth(WIDTH - 2 * COLUMNS[1])
	frame.footer:SetJustifyH("LEFT")
	return frame
end

-- Az ablak be- és kikapcsolása (megjegyzi: a következő belépéskor is így lesz).
function ns.ShowWindow(show)
	WoWLevelingDB.window.hidden = not show
	if show then
		window = window or CreateWindow()
		window:Show()
		RefreshWindow()
	elseif window then
		window:Hide()
		tracking = false
	end
end

local function StartWindow()
	if not WoWLevelingDB.window.hidden then
		ns.ShowWindow(true)
	end
	if C_Timer and C_Timer.NewTicker then
		C_Timer.NewTicker(60, function() -- éjfél után új nap: új szintcélok
			if window and window:IsShown() and Today() ~= shownDay then
				RefreshWindow()
			end
		end)
	end
end

SLASH_WOWLEVELING1 = "/wowleveling"
SLASH_WOWLEVELING2 = "/wowlvl"
SlashCmdList.WOWLEVELING = function(message)
	InitDB()
	local current = Save()
	local command = (message or ""):match("^%s*(.-)%s*$"):lower()
	if command == "ablak" or command == "window" then
		ns.ShowWindow(not (window and window:IsShown()))
		return
	end
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
	Print("A lemaradás ablaka: /wowleveling ablak")
end

local started = false
local frame = CreateFrame("Frame")
frame:SetScript("OnEvent", function(_, event, arg1)
	if event == "ADDON_LOADED" then
		if arg1 == ADDON_NAME then
			InitDB()
		end
	elseif event == "PLAYER_LOGOUT" then
		Save() -- az utolsó esemény, mielőtt a játék kiírja a mentett adatokat
	elseif event == "PLAYER_XP_UPDATE" then
		if tracking then
			RefreshSoon()
		end
	elseif event == "PLAYER_SPECIALIZATION_CHANGED" then
		if arg1 == nil or arg1 == "player" then
			SaveSoon(1)
		end
	elseif event == "CHALLENGE_MODE_COMPLETED" then
		SaveSoon(5) -- a Mythic+ pontszám kicsit később frissül
		if tracking and C_Timer and C_Timer.After then
			C_Timer.After(6, RefreshWindow)
		end
	else
		SaveSoon(2)
		if event == "PLAYER_ENTERING_WORLD" and not started then
			started = true
			if C_Timer and C_Timer.After then
				C_Timer.After(3, StartWindow) -- addigra betöltődnek a tárgyak adatai is
			else
				StartWindow()
			end
		elseif tracking then
			RefreshSoon()
		end
	end
end)

for _, event in ipairs({
	"ADDON_LOADED",
	"PLAYER_ENTERING_WORLD",
	"PLAYER_LEVEL_UP",
	"PLAYER_XP_UPDATE",
	"PLAYER_EQUIPMENT_CHANGED",
	"PLAYER_AVG_ITEM_LEVEL_UPDATE",
	"PLAYER_SPECIALIZATION_CHANGED",
	"CHALLENGE_MODE_COMPLETED",
	"PLAYER_LOGOUT",
}) do
	pcall(frame.RegisterEvent, frame, event) -- egy esetleg megszűnt esemény se okozzon hibát
end
