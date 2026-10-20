-- A gear ajánló a játékban: melyik tartalom (dungeon, Mythic+, delve, prey, raid…) ad még
-- fejlesztést a karakter itemleveléhez – dropból, csak a Great Vaultból, túl alacsony hozzá az
-- itemlevel, vagy már kinőtte.
--
-- Pontosan azt számolja, amit a program gear ajánlója (gearing.py: evaluate, best_reachable_row,
-- build_items). A tartalmak adatait (a belépési, a drop és a Vault ilvl-t, a statisztikákból
-- frissített belépési ilvl-ekkel) a program a PlanData.lua fájlba szinkronizálja (lásd
-- wow_addon.py: gear_payload), századokban (311,6 -> 31160).
--
-- Az ablakot a /wowleveling gear parancs és a lemaradás ablakának Gear gombja nyitja meg; a
-- karakter itemlevelének változásakor magától frissül.

local _, ns = ...
local Gear = {}
ns.Gear = Gear

local MIN_ILVL = 1 -- a 0 (nincs korlát) belépési ilvl így látszik, mint a programban

-- Az állapotok: a rendezés sorrendje, a felirat és a színe.
Gear.STATUSES = {
	recommended = { priority = 1, label = "Irány farmolni!", color = "ff40e060" },
	vault = { priority = 2, label = "Csak Vaultért", color = "ffffd100" },
	undergeared = { priority = 3, label = "Túl alacsony ilvl", color = "ffff6060" },
	outgrown = { priority = 4, label = "Túlfejlett vagy", color = "ff999999" },
}
local STATUSES = Gear.STATUSES

-- Legfeljebb 2 tizedes, felesleges nullák nélkül, tizedesvesszővel (288, 291,5).
function Gear.FormatIlvl(value)
	local text = string.format("%.2f", value):gsub("0+$", ""):gsub("%.$", "")
	return (text:gsub("%.", ","))
end
local FormatIlvl = Gear.FormatIlvl

-- A szinkronizált adatok csoportjai: { id, label, tiered, rows = { name, entry, drop, vault } },
-- az itemlevelek már tizedes számként (a vault nil, ha nincs érdemi Vault-plafon).
function Gear.Groups(gearData)
	local groups = {}
	for _, source in ipairs(type(gearData) == "table" and gearData.groups or {}) do
		local group = { id = source.id, label = source.label, tiered = source.tiered == true, rows = {} }
		for _, row in ipairs(source.rows or {}) do
			group.rows[#group.rows + 1] = {
				name = row.name,
				entry = (row.entry or 0) / 100,
				drop = row.drop / 100,
				vault = row.vault and row.vault / 100,
			}
		end
		groups[#groups + 1] = group
	end
	return groups
end

local function Ceiling(row) -- a Vaultból elérhető legmagasabb ilvl (Vault-plafon nélkül a drop)
	return row.vault or row.drop
end

-- Megéri-e a tartalom ezzel az itemlevellel (gearing.evaluate): az állapot, a rendezési súly
-- (gain: nagyobb = előrébb az állapoton belül) és a megjegyzés.
function Gear.Evaluate(ilvl, row)
	local ceiling = Ceiling(row)
	if ilvl < row.entry then
		local missing = row.entry - ilvl
		return { row = row, status = "undergeared", gain = -missing, note = FormatIlvl(missing) .. " ilvl hiányzik" }
	end
	if ilvl < row.drop then
		local gain = row.drop - ilvl
		return { row = row, status = "recommended", gain = gain, note = "dropból még +" .. FormatIlvl(gain) .. " ilvl" }
	end
	if ilvl < ceiling then
		local gain = ceiling - ilvl
		return { row = row, status = "vault", gain = gain, note = "Vaultból még +" .. FormatIlvl(gain) .. " ilvl" }
	end
	return { row = row, status = "outgrown", gain = ceiling - ilvl, note = "" }
end

-- A tier-es csoport legjobb elérhető tierje: az utolsó, amelynek a belépési ilvl-jét már eléri;
-- ha egyiket sem, az első.
function Gear.BestReachableRow(group, ilvl)
	local best = group.rows[1]
	for _, row in ipairs(group.rows) do
		if ilvl >= row.entry then
			best = row
		end
	end
	return best
end

-- A megjelenítendő sorok (gearing.build_items): az active csoportokból (id -> true), a tier-es
-- csoportokból – ha nem kell minden tier – csak a legjobb elérhető; az állapot szerint
-- rendezve, azon belül a nagyobb nyereség, majd a magasabb Vault-plafon előre (egyezésnél az
-- adatok sorrendje marad). Itemlevel nélkül értékelés nélkül, az adatok sorrendjében.
function Gear.BuildItems(groups, ilvl, active, showAll)
	local collapse = ilvl ~= nil and not showAll
	local rows = {}
	for _, group in ipairs(groups) do
		if active[group.id] then
			if collapse and group.tiered and #group.rows > 0 then
				rows[#rows + 1] = Gear.BestReachableRow(group, ilvl)
			else
				for _, row in ipairs(group.rows) do
					rows[#rows + 1] = row
				end
			end
		end
	end
	local items = {}
	for index, row in ipairs(rows) do
		local item = ilvl and Gear.Evaluate(ilvl, row) or { row = row, note = "" }
		item.index = index
		items[index] = item
	end
	if ilvl then
		table.sort(items, function(a, b)
			local first, second = STATUSES[a.status].priority, STATUSES[b.status].priority
			if first ~= second then
				return first < second
			end
			if a.gain ~= b.gain then
				return a.gain > b.gain
			end
			if Ceiling(a.row) ~= Ceiling(b.row) then
				return Ceiling(a.row) > Ceiling(b.row)
			end
			return a.index < b.index
		end)
	end
	return items
end

-- === Az ablak ===

local WIDTH, HEIGHT = 620, 304
local VISIBLE = 12 -- ennyi sor látszik egyszerre (egérgörgővel görgethető)
local ROW_HEIGHT = 15
local COLUMNS = { -- a sorok oszlopai: kulcs, felirat, x, szélesség
	{ key = "name", label = "Tartalom", x = 10, width = 205 },
	{ key = "entry", label = "Belépés", x = 220, width = 48 },
	{ key = "drop", label = "Drop", x = 270, width = 40 },
	{ key = "vault", label = "Vault", x = 312, width = 44 },
	{ key = "status", label = "Ajánlás", x = 360, width = 102 },
	{ key = "note", label = "Megjegyzés", x = 464, width = 150 },
}
local window
local offset = 0 -- az első látható sor előtti sorok száma
local refreshScheduled = false

local function Settings()
	if type(WoWLevelingDB.gear) ~= "table" then
		WoWLevelingDB.gear = {}
	end
	local settings = WoWLevelingDB.gear
	if type(settings.off) ~= "table" then
		settings.off = {} -- a kikapcsolt tartalomtípusok (alapból mind látszik)
	end
	return settings
end

local function Colored(color, text)
	return "|c" .. color .. text .. "|r"
end

local function SetChip(chip, on)
	chip.text:SetText(Colored(on and "ffffffff" or "ff777777", chip.label))
end

local function CreateChip(parent, label, onClick)
	local chip = CreateFrame("Button", nil, parent)
	chip.label = label
	chip.text = chip:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
	chip.text:SetPoint("CENTER")
	chip.text:SetText(label)
	local width = chip.text:GetStringWidth()
	chip:SetSize((type(width) == "number" and width or #label * 6) + 12, 16)
	chip:SetScript("OnClick", onClick)
	return chip
end

-- A tartalomtípusok szűrői (a szinkronizált csoportokból, egyszer) és a „minden tier” kapcsoló.
local function CreateChips(groups)
	local previous
	window.chips = {}
	for _, group in ipairs(groups) do
		local chip = CreateChip(window, group.label, function()
			local off = Settings().off
			off[group.id] = not off[group.id] or nil
			offset = 0
			Gear.Refresh()
		end)
		chip.id = group.id
		if previous then
			chip:SetPoint("LEFT", previous, "RIGHT", 4, 0)
		else
			chip:SetPoint("TOPLEFT", 6, -44)
		end
		window.chips[#window.chips + 1] = chip
		previous = chip
	end
	window.showAll = CreateChip(window, "minden tier", function()
		local settings = Settings()
		settings.showAll = not settings.showAll or nil
		offset = 0
		Gear.Refresh()
	end)
	window.showAll:SetPoint("LEFT", previous, "RIGHT", 14, 0)
end

local function SetRow(cells, values, color)
	for _, column in ipairs(COLUMNS) do
		local text = values and values[column.key] or ""
		if color and (column.key == "status" or column.key == "note") and text ~= "" then
			text = Colored(color, text)
		end
		cells[column.key]:SetText(text)
	end
end

local function Render()
	local data = WoWLevelingPlanData
	local gearData = type(data) == "table" and data.gear or nil
	local ilvl = ns.EquippedItemLevel and ns.EquippedItemLevel()
	local name = UnitName("player")
	if ilvl then
		window.ilvl:SetText("Itemlevel: " .. FormatIlvl(ilvl) .. (type(name) == "string" and (" (" .. name .. ")") or ""))
	else
		window.ilvl:SetText("Itemlevel: most nem ismert")
	end
	local groups = Gear.Groups(gearData)
	if #groups == 0 then
		SetRow(window.rows[1], { name = Colored("ff999999", "Még nincs szinkronizált gear-adat.") })
		SetRow(window.rows[2], { name = Colored("ff999999", "A programban: Szinkronizálás, majd /reload.") })
		for index = 3, VISIBLE do
			SetRow(window.rows[index])
		end
		window.summary:SetText("")
		window.source:SetText("")
		return
	end
	if not window.chips then
		CreateChips(groups)
	end
	local settings = Settings()
	local active = {}
	for _, chip in ipairs(window.chips) do
		active[chip.id] = not settings.off[chip.id]
		SetChip(chip, active[chip.id])
	end
	SetChip(window.showAll, settings.showAll)

	local items = Gear.BuildItems(groups, ilvl, active, settings.showAll)
	offset = math.max(0, math.min(offset, #items - VISIBLE))
	for index = 1, VISIBLE do
		local item = items[offset + index]
		if item then
			local row, status = item.row, item.status and STATUSES[item.status]
			SetRow(window.rows[index], {
				name = row.name,
				entry = FormatIlvl(math.max(row.entry, MIN_ILVL)),
				drop = FormatIlvl(row.drop),
				vault = row.vault and FormatIlvl(row.vault) or "Nincs",
				status = status and status.label or "-",
				note = item.note,
			}, status and status.color)
		elseif index == 1 then
			SetRow(window.rows[index], { name = Colored("ff999999", "Nincs bekapcsolva tartalomtípus.") })
		else
			SetRow(window.rows[index])
		end
	end

	local recommended = 0
	for _, item in ipairs(items) do
		if item.status == "recommended" then
			recommended = recommended + 1
		end
	end
	local summary = #items .. " sor, ajánlott: " .. recommended
	if #items > VISIBLE then
		summary = summary .. " · " .. (offset + 1) .. "-" .. math.min(offset + VISIBLE, #items)
			.. ". sor látszik (görgess az egérrel)"
	end
	window.summary:SetText(summary)
	local updated = tonumber(gearData.updated) or 0
	local source = updated > 0 and ("Belépési ilvl-ek: " .. updated .. " sor a statisztikákból frissítve")
		or "Belépési ilvl-ek: az alapértékek"
	window.source:SetText(source .. " · szinkronizálva: " .. date("%Y-%m-%d %H:%M", tonumber(data.generated) or 0))
end

-- Az ablak újraszámolása; egy váratlan hiba csak az ablakban látszik, a játékot nem zavarja.
function Gear.Refresh()
	refreshScheduled = false
	if not window or not window:IsShown() then
		return
	end
	local ok, problem = pcall(Render)
	if not ok then
		window.summary:SetText(Colored("ffff6060", "hiba: " .. tostring(problem)))
	end
end

local function RefreshSoon()
	if refreshScheduled or not window or not window:IsShown() then
		return
	end
	if C_Timer and C_Timer.After then
		refreshScheduled = true
		C_Timer.After(1, Gear.Refresh)
	else
		Gear.Refresh()
	end
end

local function SavePosition(frame)
	local point, _, relativePoint, x, y = frame:GetPoint()
	local settings = Settings()
	settings.point, settings.relativePoint, settings.x, settings.y = point, relativePoint, x, y
end

local function CreateWindow()
	local frame = CreateFrame("Frame", "WoWLevelingGearWindow", UIParent, BackdropTemplateMixin and "BackdropTemplate" or nil)
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
	frame:EnableMouseWheel(true)
	frame:SetScript("OnMouseWheel", function(_, delta)
		offset = offset - delta * 3
		Gear.Refresh()
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
		frame:SetBackdropColor(0, 0, 0, 0.8)
	end
	local settings = Settings()
	frame:SetPoint(settings.point or "CENTER", UIParent, settings.relativePoint or "CENTER", settings.x or 0, settings.y or -80)

	local title = frame:CreateFontString(nil, "OVERLAY", "GameFontNormal")
	title:SetPoint("TOPLEFT", 10, -9)
	title:SetText("WoWLeveling - gear ajánló")
	local close = CreateFrame("Button", nil, frame, "UIPanelCloseButton")
	close:SetPoint("TOPRIGHT", 0, 0)
	close:SetScript("OnClick", function()
		Gear.ShowWindow(false)
	end)
	frame.ilvl = frame:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
	frame.ilvl:SetPoint("TOPLEFT", 10, -27)

	for _, column in ipairs(COLUMNS) do
		local header = frame:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
		header:SetPoint("TOPLEFT", column.x, -66)
		header:SetText(column.label)
	end
	frame.rows = {}
	for index = 1, VISIBLE do
		local cells = {}
		for _, column in ipairs(COLUMNS) do
			local cell = frame:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
			cell:SetPoint("TOPLEFT", column.x, -68 - index * ROW_HEIGHT)
			cell:SetWidth(column.width)
			cell:SetJustifyH("LEFT")
			cell:SetWordWrap(false)
			cells[column.key] = cell
		end
		frame.rows[index] = cells
	end
	frame.summary = frame:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
	frame.summary:SetPoint("BOTTOMLEFT", 10, 24)
	frame.source = frame:CreateFontString(nil, "OVERLAY", "GameFontDisableSmall")
	frame.source:SetPoint("BOTTOMLEFT", 10, 9)
	return frame
end

-- Az ablak be- és kikapcsolása (megjegyzi: a következő belépéskor is így lesz).
function Gear.ShowWindow(show)
	Settings().shown = show or nil
	if show then
		window = window or CreateWindow()
		window:Show()
		Gear.Refresh()
	elseif window then
		window:Hide()
	end
end

function Gear.Toggle()
	Gear.ShowWindow(not (window and window:IsShown()))
end

-- Belépéskor: ha legutóbb nyitva volt, újra megnyitja.
function Gear.Start()
	if Settings().shown then
		Gear.ShowWindow(true)
	end
end

-- A felszerelés változásakor (ha látszik az ablak) újraszámol.
local events = CreateFrame("Frame")
events:SetScript("OnEvent", RefreshSoon)
for _, event in ipairs({ "PLAYER_EQUIPMENT_CHANGED", "PLAYER_AVG_ITEM_LEVEL_UPDATE" }) do
	pcall(events.RegisterEvent, events, event)
end
