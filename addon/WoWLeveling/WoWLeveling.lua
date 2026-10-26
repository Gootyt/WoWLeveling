-- WoWLeveling: elmenti a karakterek adatait a WoW szintezés tervező programnak.
--
-- Minden karakterről, amellyel belépsz, elmenti a nevét, a realmjét, a régióját, a faját,
-- a kasztját, az aktív specjét, a szintjét két tizedesre (a tapasztalattal együtt, pl. 85.29),
-- a felvett tárgyak átlagos itemlevelét és a Mythic+ pontszámát. Az adatokat játék közben
-- folyamatosan frissíti (tapasztalat, szintlépés, felszerelés, spec, Mythic+), de a fájlba a
-- játék csak kilépéskor, kijelentkezéskor és /reload után írja ki őket (máskor egy addon sem
-- tudja kiíratni), a fiók mappájába. Kilépéskor már nem olvas a játékból, mert az ekkor a
-- tapasztalatra és a specre 0-t ad vissza: a fájlba a legutóbbi, játék közbeni állapot kerül.
--
--   World of Warcraft\_retail_\WTF\Account\<FIÓK>\SavedVariables\WoWLeveling.lua
--
-- Azonnal a /wowleveling mentés paranccsal vagy az ablak Mentés gombjával lehet kiíratni őket:
-- ezek újratöltik a felületet (/reload). A program (wow_leveling.py) innen olvassa be őket:
-- indításkor, futás közben pedig magától, amint a játék kiírta őket, és a főablak
-- „Importálás most” gombjával.
--
-- Egy kis ablakban azt is mutatja, melyik karakter van a legnagyobb lemaradásban szintben,
-- itemlevelben és Mythic+ pontszámban, alatta pedig a belépett karakter saját lemaradását (vagy
-- előnyét) ugyanebben a háromban (a program terve szerint, amelyet a program a PlanData.lua
-- fájlba szinkronizál; a számolás a Plan.lua-ban van). Ha a terv egyik karakterével játszol, az
-- ablak a játékbeli adatokból magától frissül.
--
-- Parancsok: /wowleveling (vagy /wowlvl): a karakter elmentett adatai és a lemaradása;
--            /wowleveling lista: az összes elmentett karakter;
--            /wowleveling ablak: a lemaradás ablakának be- és kikapcsolása;
--            /wowleveling gear: a gear ajánló be- és kikapcsolása (lásd Gear.lua);
--            /wowleveling mentés: az adatok kiíratása most (a felület újratöltésével).

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

-- Az addon változata a .toc fájlból: a mentésbe is beírja, így a program látja, ha a játék még
-- a frissítés előtti változatot futtatja.
local function AddonVersion()
	local getMetadata = C_AddOns and C_AddOns.GetAddOnMetadata or GetAddOnMetadata
	if not getMetadata then
		return nil
	end
	local ok, version = pcall(getMetadata, ADDON_NAME, "Version")
	return ok and Plain(version) or nil
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
	if type(index) ~= "number" or index < 1 then
		return nil, nil
	end
	local specID, specName = getInfo(index)
	specID, specName = Plain(specID), Plain(specName)
	if type(specID) ~= "number" or specID < 1 then -- ha a játék épp nem tudja, 0-t ad vissza
		specID = nil
	end
	if type(specName) ~= "string" or specName == "" then
		specName = nil
	end
	return specID, specName
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

ns.EquippedItemLevel = EquippedItemLevel -- a gear ajánlónak (Gear.lua)

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
	WoWLevelingDB.addonVersion = AddonVersion()
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
	if type(xp) ~= "number" or type(xpMax) ~= "number" or xp < 0 or xpMax <= 0 then
		xp, xpMax = nil, nil -- a játék most nem tudja (pl. kilépés közben 0-t ad): a korábbi érték marad
	end
	local key = name .. "-" .. realm
	local entry = WoWLevelingDB.characters[key]
	local level = LevelValue(Plain(UnitLevel("player")), xp, xpMax)
	local keepXP = false -- a korábbi tapasztalat és a vele együtt mentett szint marad
	if level and not xpMax and type(entry) == "table" then
		local saved = LevelValue(entry.level, entry.xp, entry.xpMax)
		keepXP = saved ~= nil and math.floor(saved / 100) == math.floor(level / 100)
		level = keepXP and saved or level
	end
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
	if type(entry) ~= "table" then
		entry = {}
		WoWLevelingDB.characters[key] = entry
	end
	for field, value in pairs(fresh) do -- ami most nem ismert, az a korábbi értéken marad
		entry[field] = value
	end
	if level and not xpMax and not keepXP then
		entry.xp, entry.xpMax = nil, nil -- új szint, de a tapasztalata most nem ismert
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

-- Az adatok kiíratása most: a játék csak kilépéskor, kijelentkezéskor és a felület újratöltésekor
-- írja ki a mentett adatokat, ezért ez a friss adatok mentése után újratölti a felületet. A játék
-- csak a játékos kattintására vagy parancsára engedi.
local function SaveNow()
	Save()
	local reload = C_UI and C_UI.Reload or ReloadUI
	if reload then
		reload()
	end
end

-- Az ablak Mentés gombja előbb megkérdezi, mert az újratöltés egy rövid töltőképernyővel jár.
local function ConfirmSaveNow()
	if not (StaticPopupDialogs and StaticPopup_Show) then
		SaveNow()
		return
	end
	StaticPopupDialogs.WOWLEVELING_SAVE_NOW = StaticPopupDialogs.WOWLEVELING_SAVE_NOW or {
		text = "WoWLeveling: a játék csak a felület újratöltésekor (/reload) írja ki az adatokat, "
			.. "a futó program ezután magától beolvassa az új mentést. Újratöltsem most a felületet?",
		button1 = "Igen",
		button2 = "Nem",
		OnAccept = function()
			SaveNow()
		end,
		timeout = 0,
		whileDead = true,
		hideOnEscape = true,
		preferredIndex = 3,
	}
	StaticPopup_Show("WOWLEVELING_SAVE_NOW")
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

local WIDTH, HEIGHT = 370, 190 -- a lábléc két sorba is kifér
local ROWS = { -- az ablak sorai: a Plan.Compute eredményének kulcsa, felirat, a számok léptéke
	{ key = "level", label = "Szint", scale = 100, digits = 2 },
	{ key = "itemLevel", label = "Itemlevel", scale = 100, digits = 2 },
	{ key = "score", label = "Mythic+", scale = 10, digits = 1 },
}
local COLUMNS = { 10, 78, 190, 280 } -- felirat, karakter (a saját soroknál az érték), cél, hiány
local OWN_TOP = 4 * 17 + 4 -- a belépett karakter sorai ennyivel lejjebb kezdődnek
local window
local tracking = false -- a terv egyik karakterével játszik: az ablak magától frissül
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

-- A terv számolása a játékbeli adatokkal: az eredmény, és a belépett karakter a tervben (nil, ha
-- nincs benne). Az eredmény own mezőjében a belépett karakter saját sorai (lásd Plan.Compute).
local function ComputePlan(data, today)
	local chars = Plan.Characters(data, Override)
	local focus
	for _, char in ipairs(chars) do
		if IsPlayer(char.source) then
			focus = char
			break
		end
	end
	return Plan.Compute(data, chars, today, focus), focus
end

-- A belépett karakter értéke egy szempontból, a sor léptékében (a pontszám tizedekben).
local function OwnValue(focus, key)
	if key == "score" then
		return focus.score and Plan.RoundHalfUp(focus.score, 10)
	end
	return focus[key]
end

-- A belépett karakter egy sorának szövegei: az érték, a cél és az eltérés; az érték és hogy elérte
-- a célt (vagy mikor kezd); vagy csak az, hogy miért nincs mihez mérni.
local function OwnTexts(line, row, value)
	local shown = value and Number(value / row.scale, row.digits)
	if line.target then
		local amount = Number(math.abs(line.deviation) / row.scale, row.digits)
		local deviation = line.deviation < 0 and "|cffff6060hiányzik: " .. amount .. "|r"
			or line.deviation > 0 and "|cff60ff60többlet: " .. amount .. "|r"
			or "|cff60ff60terv szerint|r"
		return { shown, "cél: " .. Number(line.target / row.scale, row.digits), deviation }
	end
	local status = line.done and "|cff60ff60" .. line.done .. "|r"
		or line.notStarted and "|cff999999kezdés: " .. line.notStarted .. "|r"
	if status and shown then
		return { shown, status }
	end
	return { status or "|cff999999" .. tostring(line.problem) .. "|r" }
end

local function NotInPlanText()
	local name = Plain(UnitName("player"))
	return "Ez a karakter" .. (type(name) == "string" and name ~= "" and " (" .. name .. ")" or "") .. " nincs a tervben."
end

local function Refresh()
	local data = WoWLevelingPlanData
	local today = Today()
	shownDay = today
	local own = window.own
	if type(data) ~= "table" then
		for index, row in ipairs(ROWS) do
			local note = index == 1 and "Még nincs szinkronizált terv."
				or index == 2 and "A programban: Szinkronizálás, majd /reload."
				or nil
			SetRow(window.rows[row.key], note and ("|cff999999" .. note .. "|r"))
			SetRow(own.rows[row.key])
		end
		own.header:SetText("")
		window.footer:SetText("")
		return
	end
	local result, focus = ComputePlan(data, today)
	for _, row in ipairs(ROWS) do
		local cells, line = window.rows[row.key], result[row.key]
		if line.char then
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
		if focus then
			local texts = OwnTexts(result.own[row.key], row, OwnValue(focus, row.key))
			SetRow(own.rows[row.key], texts[1], texts[2], texts[3])
		else
			SetRow(own.rows[row.key])
		end
	end
	if focus then -- vele játszik: az ablak a játékbeli adataiból magától frissül
		tracking = true
		own.header:SetText("Ez a karakter: " .. ColoredName(focus))
	else
		own.header:SetText("|cff999999" .. NotInPlanText() .. "|r")
		SetRow(own.rows.level, "|cff999999A programban vedd fel a listára, majd Szinkronizálás.|r")
	end
	local parts = { "Szinkronizálva: " .. date("%Y-%m-%d %H:%M", tonumber(data.generated) or 0) }
	parts[#parts + 1] = GoalDayText(result.goalDay, today)
	if focus then
		parts[#parts + 1] = "automatikus frissítés: " .. focus.name
	end
	window.footer:SetText(table.concat(parts, " · "))
end

-- A /wowleveling parancshoz: a belépett karakter lemaradása a csevegőablakba (nil: nincs terv).
local function OwnLines()
	local data = WoWLevelingPlanData
	if type(data) ~= "table" then
		return nil
	end
	local result, focus = ComputePlan(data, Today())
	if not focus then
		return { NotInPlanText() }
	end
	local lines = { "A lemaradása a terv szerint:" }
	for _, row in ipairs(ROWS) do
		local texts = OwnTexts(result.own[row.key], row, OwnValue(focus, row.key))
		lines[#lines + 1] = "  " .. row.label .. ": " .. table.concat(texts, " · ")
	end
	return lines
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
	title:SetText("WoWLeveling - lemaradás")
	local close = CreateFrame("Button", nil, frame, "UIPanelCloseButton")
	close:SetPoint("TOPRIGHT", 0, 0)
	close:SetScript("OnClick", function()
		ns.ShowWindow(false)
	end)
	local save = CreateFrame("Button", nil, frame, "UIPanelButtonTemplate")
	save:SetSize(62, 18)
	save:SetPoint("TOPRIGHT", -30, -6)
	save:SetText("Mentés")
	save:SetScript("OnClick", ConfirmSaveNow)
	save:SetScript("OnEnter", function(self)
		GameTooltip:SetOwner(self, "ANCHOR_TOP")
		GameTooltip:SetText("Mentés most")
		GameTooltip:AddLine(
			"A játék csak kilépéskor, kijelentkezéskor és /reload után írja ki az adatokat. "
				.. "Ez a gomb újratölti a felületet, és a futó program magától beolvassa az új mentést.",
			1, 1, 1, true
		)
		GameTooltip:Show()
	end)
	save:SetScript("OnLeave", function()
		GameTooltip:Hide()
	end)
	frame.saveButton = save
	local gear = CreateFrame("Button", nil, frame, "UIPanelButtonTemplate")
	gear:SetSize(48, 18)
	gear:SetPoint("RIGHT", save, "LEFT", -4, 0)
	gear:SetText("Gear")
	gear:SetScript("OnClick", function()
		ns.ToggleGear()
	end)
	frame.gearButton = gear

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
	-- Alatta a belépett karakter saját sorai, ugyanezekben az oszlopokban.
	frame.own = { rows = {} }
	frame.own.header = frame:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
	frame.own.header:SetPoint("TOPLEFT", COLUMNS[1], -14 - OWN_TOP)
	for index, row in ipairs(ROWS) do
		local cells = {}
		for column, x in ipairs(COLUMNS) do
			local cell = frame:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
			cell:SetPoint("TOPLEFT", x, -14 - OWN_TOP - index * 17)
			cell:SetJustifyH("LEFT")
			cells[column] = cell
		end
		cells[1]:SetText(row.label)
		frame.own.rows[row.key] = cells
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

-- A gear ajánló (Gear.lua) be- és kikapcsolása. Az új fájlt a játék csak újraindítás után tölti
-- be (a /reload után még nem), addig ezt üzeni.
function ns.ToggleGear()
	if ns.Gear then
		ns.Gear.Toggle()
	else
		print(PREFIX .. "A gear ajánlóhoz indítsd újra a játékot: új fájl került az addonba.")
	end
end

local function StartWindow()
	if not WoWLevelingDB.window.hidden then
		ns.ShowWindow(true)
	end
	if ns.Gear then
		ns.Gear.Start()
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
	if command == "gear" then
		ns.ToggleGear()
		return
	end
	if command == "mentés" or command == "mentes" or command == "save" then
		SaveNow()
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
		local ok, lines = pcall(OwnLines) -- egy váratlan hiba ne akassza meg a parancsot
		for index, line in ipairs(ok and lines or {}) do
			print(index == 1 and PREFIX .. line or line)
		end
	else
		Print("most nem sikerült elmenteni a karakter adatait.")
	end
	if WoWLevelingDB.lastError then
		Print("hiba: " .. WoWLevelingDB.lastError)
	end
	Print("A játék kilépéskor, kijelentkezéskor és /reload után írja ki az adatokat; most rögtön: /wowleveling mentés")
	Print("A lemaradás ablaka: /wowleveling ablak · a gear ajánló: /wowleveling gear")
	if WoWLevelingDB.addonVersion then
		Print("Az addon változata: " .. WoWLevelingDB.addonVersion)
	end
end

local started = false
local frame = CreateFrame("Frame")
frame:SetScript("OnEvent", function(_, event, arg1)
	if event == "ADDON_LOADED" then
		if arg1 == ADDON_NAME then
			InitDB()
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
	else -- belépés, szintlépés, tapasztalat, felszerelés: az adatok mindig frissek, bármikor írja ki őket a játék
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
	-- A PLAYER_LOGOUT eseménynél (kilépés, kijelentkezés, /reload) nem ment: a játék ekkor már 0-t ad
	-- a tapasztalatra és a specre, a fájlba így a legutóbbi, játék közbeni mentés kerül.
}) do
	pcall(frame.RegisterEvent, frame, event) -- egy esetleg megszűnt esemény se okozzon hibát
end
