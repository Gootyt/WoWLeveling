-- A WoW szintezés tervező számításai az addon ablakához: melyik karakter van a legnagyobb
-- lemaradásban szintben, itemlevelben és Mythic+ pontszámban, mekkora értéket kell elérnie,
-- hogy ne legyen lemaradása, és mennyi hiányzik még; és ugyanez egy megadott (a belépett)
-- karakterre: mekkora a tervezett értéke, és mennyivel jár előtte vagy mögötte.
--
-- Pontosan azt számolja, amit a program (leveling.py: build_plan, lookahead_day, murlok_order,
-- plan_item_levels, plan_raiderio_scores), csak egész számokkal: a szintek és az itemlevelek
-- századokban (85,29 -> 8529), a pontszámok a bemenetnél századokban, az eredményben tizedekben.
-- A program a terv adatait a PlanData.lua fájlba írja (lásd wow_addon.py).

local _, ns = ...
local Plan = {}
ns.Plan = Plan

local floor = math.floor

-- A napok sorszáma egy rögzített naptól (polgári naptár, Howard Hinnant algoritmusa).
function Plan.DayNumber(year, month, day)
	if month <= 2 then
		year = year - 1
	end
	local era = floor(year / 400)
	local yearOfEra = year - era * 400
	local dayOfYear = floor((153 * ((month + 9) % 12) + 2) / 5) + day - 1
	local dayOfEra = yearOfEra * 365 + floor(yearOfEra / 4) - floor(yearOfEra / 100) + dayOfYear
	return era * 146097 + dayOfEra - 719468
end

-- "2026-10-17" -> napszám (hibás szövegnél nil).
function Plan.ParseDay(text)
	local year, month, day = tostring(text or ""):match("^(%d+)-(%d+)-(%d+)$")
	if not year then
		return nil
	end
	return Plan.DayNumber(tonumber(year), tonumber(month), tonumber(day))
end

-- A tört (számláló / nevező, a nevező pozitív) kerekítése egészre, a felénél a nullától el.
local function RoundHalfUp(numerator, denominator)
	if numerator >= 0 then
		return floor((2 * numerator + denominator) / (2 * denominator))
	end
	return -floor((-2 * numerator + denominator) / (2 * denominator))
end
Plan.RoundHalfUp = RoundHalfUp

-- Stabil rendezés (az egyenlők sorrendje marad, mint a Pythonban): before(a, b) igaz, ha a előbb jön.
local function StableSort(list, before)
	for index = 2, #list do
		local item = list[index]
		local place = index - 1
		while place >= 1 and before(item, list[place]) do
			list[place + 1] = list[place]
			place = place - 1
		end
		list[place + 1] = item
	end
	return list
end

-- A day nap végéig elérendő szint (lásd leveling.planned_level).
local function PlannedLevel(start, deadline, from, to, day)
	if day < start then
		return from
	end
	if day >= deadline then
		return to
	end
	local total = deadline - start + 1
	local elapsed = day - start + 1
	return from + floor((to - from) * elapsed / total)
end
Plan.PlannedLevel = PlannedLevel

-- Az első nap a mai naptól, amelynek tervezett szintjét még nem érte el minden karakter
-- (lásd leveling.lookahead_day).
local function LookaheadDay(data, chars, today)
	local allDone = true
	local lastDay
	for _, char in ipairs(chars) do
		if char.level < data.targetLevel then
			allDone = false
		end
		if not lastDay or char.deadline > lastDay then
			lastDay = char.deadline
		end
	end
	if allDone then
		return today
	end
	local day = today
	while day < lastDay do
		for _, char in ipairs(chars) do
			if char.level < PlannedLevel(char.start, char.deadline, data.startLevel, data.targetLevel, day) then
				return day
			end
		end
		day = day + 1
	end
	return day
end

-- Szintezési sorrend a Murlok.io-pontszámok alapján (lásd leveling.murlok_order).
local function MurlokOrder(chars)
	local groups, keys, unranked = {}, {}, {}
	for _, char in ipairs(chars) do
		if char.specScore then
			local group = groups[char.specKey]
			if not group then
				group = {}
				groups[char.specKey] = group
				keys[#keys + 1] = char.specKey
			end
			group[#group + 1] = char
		else
			unranked[#unranked + 1] = char
		end
	end
	local rounds = 0
	for _, key in ipairs(keys) do
		StableSort(groups[key], function(a, b)
			return a.level > b.level
		end)
		rounds = math.max(rounds, #groups[key])
	end
	StableSort(keys, function(a, b)
		return groups[a][1].specScore > groups[b][1].specScore
	end)
	local order = {}
	for round = 1, rounds do
		for _, key in ipairs(keys) do
			if groups[key][round] then
				order[#order + 1] = groups[key][round]
			end
		end
	end
	for _, char in ipairs(unranked) do
		order[#order + 1] = char
	end
	return order
end
Plan.MurlokOrder = MurlokOrder

-- Elérte-e a karakter a célitemlevelt: ekkor az itemlevel- és a pontszámtervből kimarad.
local function Reached(data, char)
	return data.targetItemLevel and char.itemLevel and char.itemLevel >= data.targetItemLevel
end

local function NotReached(data, chars)
	local remaining = {}
	for _, char in ipairs(chars) do
		if not Reached(data, char) then
			remaining[#remaining + 1] = char
		end
	end
	return remaining
end

-- Tervezett itemlevelek (lásd leveling.plan_item_levels): karakter -> érték, vagy nil és az ok.
local function ItemLevelPlan(data, chars)
	local target = data.targetItemLevel
	if not target then
		return nil, "nincs megadva célitemlevel"
	end
	local remaining = NotReached(data, chars)
	if #remaining == 0 then
		return nil, "mindenki elérte a célitemlevelt"
	end
	local order = MurlokOrder(remaining)
	local ratios = {}
	for position, char in ipairs(order) do
		if char.itemLevel then
			ratios[#ratios + 1] = { numerator = target - char.itemLevel, denominator = position }
		end
	end
	if #ratios < 2 then
		return nil, "legalább két karakternél kell itemlevel"
	end
	StableSort(ratios, function(a, b) -- csökkenő sorrend, a törteket keresztbe szorozva
		return a.numerator * b.denominator > b.numerator * a.denominator
	end)
	local step = ratios[2]
	local planned = {}
	for position, char in ipairs(order) do
		local numerator = target * step.denominator - position * step.numerator
		planned[char] = math.max(0, RoundHalfUp(numerator, step.denominator))
	end
	return planned
end

-- Tervezett Mythic+ pontszámok tizedekben (lásd leveling.plan_raiderio_scores).
local function ScorePlan(data, chars)
	if not data.specScores then
		return nil, "nincsenek Murlok.io-pontszámok"
	end
	local order = MurlokOrder(NotReached(data, chars))
	local anchors = {}
	for position, char in ipairs(order) do
		if char.specScore and char.specScore ~= 0 and char.score then
			anchors[#anchors + 1] = { position = position, char = char }
		end
	end
	if #anchors < 2 then
		return nil, "legalább két karakternél kell pontszám"
	end
	local anchor = anchors[2]
	local specScore, score, position = anchor.char.specScore, anchor.char.score, anchor.position
	local planned = {}
	for index, char in ipairs(order) do
		if char.specScore then
			local numerator = char.specScore * (position * specScore - index * (specScore - score))
			planned[char] = math.max(0, RoundHalfUp(numerator, 10 * position * specScore))
		end
	end
	return planned
end

-- A legnagyobb lemaradás egy szempontból: a lista sorrendjében az első a legkisebb (negatív)
-- eltéréssel. value(char) a karakter értéke, planned(char) a tervezett (nil: nem számít).
local function MostBehind(chars, value, planned)
	local best, bestDeviation, bestTarget
	for _, char in ipairs(chars) do
		local current, target = value(char), planned(char)
		if current and target then
			local deviation = current - target
			if not bestDeviation or deviation < bestDeviation then
				best, bestDeviation, bestTarget = char, deviation, target
			end
		end
	end
	if not best then
		return { problem = "nincs adat" }
	end
	if bestDeviation >= 0 then
		return { ok = true }
	end
	return { char = best, target = bestTarget, missing = -bestDeviation }
end

-- Egy karakter eltérése a tervtől egy szempontból: { target, deviation } (deviation = érték −
-- tervezett, +: a terv felett), vagy { problem = missing }, ha a karakter értéke nem ismert.
local function Deviation(current, target, missing)
	if not current then
		return { problem = missing }
	end
	return { target = target, deviation = current - target }
end

-- A terv karakterei a számoláshoz. override(char) a program adatánál frissebb értékeket adhatja
-- vissza (szint és itemlevel századokban, pontszám századokban; nil: marad a programé).
function Plan.Characters(data, override)
	local chars = {}
	for index, source in ipairs(data.characters or {}) do
		local char = {
			index = index,
			source = source,
			name = source.name,
			realm = source.realm,
			class = source.class,
			level = source.level,
			itemLevel = source.itemLevel,
			score = source.score,
			specKey = source.specKey,
			specScore = source.specScore,
			start = Plan.ParseDay(source.start) or 0,
			deadline = Plan.ParseDay(source.deadline) or 0,
		}
		if override then
			local level, itemLevel, score = override(source)
			char.level = level or char.level
			char.itemLevel = itemLevel or char.itemLevel
			char.score = score or char.score
		end
		chars[#chars + 1] = char
	end
	return chars
end

-- A három sor: { level = sor, itemLevel = sor, score = sor }. Egy sor { char, target, missing }
-- (a lemaradás), { ok = true } (senki sincs lemaradásban) vagy { problem = "ok" }.
--
-- focus: a chars egyik karaktere (a belépett), vagy nil. Ha meg van adva, az own mezőben a saját
-- három sora is benne van, ugyanúgy, ahogy a program listája mutatja: { target, deviation } (lásd
-- Deviation), { done = "ok" } (elérte a célt), { notStarted = "ÉÉÉÉ-HH-NN" } (a kezdőnapja előtt
-- legalább a kezdőszinten van), vagy { problem = "ok" }.
function Plan.Compute(data, chars, today, focus)
	local result = {}
	if #chars == 0 then
		local empty = { problem = "a tervben nincs karakter" }
		return { level = empty, itemLevel = empty, score = empty, goalDay = today }
	end
	local goalDay = data.lookAhead and LookaheadDay(data, chars, today) or today
	local function LevelGoal(char)
		return PlannedLevel(char.start, char.deadline, data.startLevel, data.targetLevel, goalDay)
	end
	result.level = MostBehind(chars, function(char)
		return char.level
	end, LevelGoal)
	result.goalDay = goalDay
	local own = focus and {}
	result.own = own
	if own then
		if focus.level >= data.targetLevel then
			own.level = { done = "elérte a célszintet" }
		elseif goalDay < focus.start and focus.level >= data.startLevel then
			own.level = { notStarted = focus.source.start }
		else -- a kezdőnapja előtt a kezdőszint a cél (ha az alatt van, lemaradásban van)
			own.level = Deviation(focus.level, LevelGoal(focus))
		end
	end

	local planned, reason = ItemLevelPlan(data, chars)
	if planned then
		result.itemLevel = MostBehind(chars, function(char)
			return char.itemLevel
		end, function(char)
			return planned[char]
		end)
	else
		result.itemLevel = { problem = reason }
	end
	if own then
		if Reached(data, focus) then
			own.itemLevel = { done = "elérte a célitemlevelt" }
		elseif not planned then
			own.itemLevel = { problem = reason }
		else
			own.itemLevel = Deviation(focus.itemLevel, planned[focus], "nincs itemlevel")
		end
	end

	planned, reason = ScorePlan(data, chars)
	local function Score(char) -- a pontszám tizedekben
		return char.score and RoundHalfUp(char.score, 10)
	end
	if planned then
		result.score = MostBehind(chars, Score, function(char)
			return planned[char]
		end)
	else
		result.score = { problem = reason }
	end
	if own then
		if Reached(data, focus) then -- a pontszámtervből is kimarad
			own.score = { done = "elérte a célitemlevelt" }
		elseif not planned then
			own.score = { problem = reason }
		elseif not planned[focus] then
			own.score = { problem = "a specjének nincs Murlok.io-pontszáma" }
		else
			own.score = Deviation(Score(focus), planned[focus], "nincs Mythic+ pontszám")
		end
	end
	return result
end
