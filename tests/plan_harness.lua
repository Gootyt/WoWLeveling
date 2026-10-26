-- Az addon számolásának (Plan.lua) kipróbálása a játék nélkül (lásd test_wow_addon.py).
--
--   lua plan_harness.lua <Plan.lua> <esetek.lua> <eredmények.lua>
--
-- Az esetek fájlja a Cases táblát adja meg: { { data = <a PlanData.lua táblája>, today =
-- "ÉÉÉÉ-HH-NN" }, ... }. Minden esetre kiszámolja a három sort, és minden karakterre a saját
-- három sorát is (mintha azzal lépett volna be), és Results néven kiírja.

local planPath, casesPath, outputPath = arg[1], arg[2], arg[3]
local ns = {}
assert(loadfile(planPath))("WoWLeveling", ns)
local Plan = ns.Plan
assert(loadfile(casesPath))()

local function Row(row)
	if row.char then
		return string.format(
			"{ name = %q, target = %d, missing = %d }",
			row.char.name,
			row.target,
			row.missing
		)
	end
	if row.ok then
		return "{ ok = true }"
	end
	return string.format("{ problem = %q }", row.problem)
end

local function Own(row)
	if row.target then
		return string.format("{ target = %d, deviation = %d }", row.target, row.deviation)
	end
	if row.done then
		return string.format("{ done = %q }", row.done)
	end
	if row.notStarted then
		return string.format("{ notStarted = %q }", row.notStarted)
	end
	return string.format("{ problem = %q }", row.problem)
end

local out = { "Results = {\n" }
for _, case in ipairs(Cases) do
	local today = Plan.ParseDay(case.today)
	local chars = Plan.Characters(case.data)
	local result = Plan.Compute(case.data, chars, today)
	local own = {}
	for _, focus in ipairs(chars) do
		local rows = Plan.Compute(case.data, chars, today, focus).own
		own[#own + 1] = string.format(
			"{ level = %s, itemLevel = %s, score = %s }",
			Own(rows.level),
			Own(rows.itemLevel),
			Own(rows.score)
		)
	end
	out[#out + 1] = string.format(
		"\t{ level = %s, itemLevel = %s, score = %s, goalDay = %d, own = { %s } },\n",
		Row(result.level),
		Row(result.itemLevel),
		Row(result.score),
		result.goalDay or -1,
		table.concat(own, ", ")
	)
end
out[#out + 1] = "}\n"
local file = assert(io.open(outputPath, "wb"))
file:write(table.concat(out))
file:close()
