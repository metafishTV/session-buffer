#!/usr/bin/env python3
"""One-time script: Create alpha entries for 4 missing sources.

Sources with distillations but no alpha cross_source entries:
1. Hosseinioun et al (2025) - Nested Human Capital
2. Jakobs/Lanigan (2016) - Communicology Chart
3. Sartre CDR2 PraxisProcess (1991)
4. Sartre CDR2 SingularityPraxis (1991)

Outputs JSON array suitable for piping to buffer_manager.py alpha-write.
"""

import json
import sys

HOSSEINIOUN_SOURCE = "Source: Hosseinioun, M., Neffke, F., Zhang, L. & Youn, H. \"Skill dependencies uncover nested human capital.\" *Nature Human Behaviour* 9, 673-687 (April 2025)."

JAKOBS_SOURCE = "Source: Richard L. Lanigan (chart attributed to Jakobs), \"Communicology: Specification of Communication Networks at Four Levels,\" 2016. Single-page systematic chart."

SARTRE_PP_SOURCE = "Source: Jean-Paul Sartre, *Critique of Dialectical Reason, Volume 2: The Intelligibility of History*, trans. Quintin Hoare, Verso, 1991, pp. 272-336."

SARTRE_SP_SOURCE = "Source: Jean-Paul Sartre, *Critique of Dialectical Reason, Volume 2*, trans. Quintin Hoare, Verso, 1991, pp. 347-392 (\"Section C: Singularity of Praxis\")."


def build_entry(source_folder, distillation, key, maps_to, ref, definition, significance, project_mapping=None, relationship=None):
    """Build a single alpha-write entry with rich body."""
    body_parts = []

    body_parts.append(f"## Definition\n{definition}")
    body_parts.append(f"## Significance\n{significance}")

    if project_mapping:
        pm = f"## Project Mapping\n\n- **Maps to**: {maps_to}"
        if relationship:
            pm += f"\n- **Relationship**: {relationship}"
        pm += f"\n- **Integration**: {project_mapping}"
        body_parts.append(pm)

    # Source citation
    sources = {
        "hosseinioun-early": HOSSEINIOUN_SOURCE,
        "jakobs-early": JAKOBS_SOURCE,
        "sartre-CDR2-praxis": SARTRE_PP_SOURCE,
        "sartre-CDR2-singularity": SARTRE_SP_SOURCE,
    }
    body_parts.append(f"## Source\n{sources[source_folder]}")

    return {
        "type": "cross_source",
        "source_folder": source_folder,
        "distillation": distillation,
        "key": key,
        "maps_to": maps_to,
        "ref": ref,
        "suggest": None,
        "body": "\n\n".join(body_parts),
    }


def hosseinioun_entries():
    """Build entries from Hosseinioun integration concepts."""
    src = "hosseinioun-early"
    dist = "Hosseinioun_etal_NestedHumanCapital_2025_Paper.md"
    entries = []

    entries.append(build_entry(src, dist,
        "Hosseinioun:asymmetric_conditional_probability",
        "cross_metathesis_directionality, initiator_responder_asymmetry",
        "§5.10",
        "Inference of directional skill dependencies via p(A|B) >> p(B|A). When one skill is almost always present given another, but not vice versa, the first is prerequisite for the second",
        "Demonstrates that co-occurrence is insufficient — directionality matters. Asymmetric conditional probabilities reveal acquisition dependencies, not just correlations. Challenges symmetric co-occurrence networks in economic complexity",
        "The paper's p(A|B) >> p(B|A) inference of directional dependency maps directly to the initiator/responder asymmetry in cross-metathesis. Agent A can absorb from Agent B but not vice versa, because A possesses prerequisite type elements that B lacks",
        "confirms"
    ))

    entries.append(build_entry(src, dist,
        "Hosseinioun:nested_hierarchy",
        "TAPS_signature_hierarchy, type_set_ordering",
        "",
        "Three-tier structure (general → intermediate → specific) with directional dependency chains. Skills categorized by demand distribution shape across occupations",
        "Maps to TAPS signature ordering. Agents with foundational signatures (broad, general) are prerequisite to agents developing specialized signatures. Informs cold-start threshold and signature-based tension classification",
        "The three-tier structure (general → intermediate → specific) maps to TAPS signature ordering. Foundational (general) type elements must be accumulated before specialized ones become accessible",
        "extends"
    ))

    entries.append(build_entry(src, dist,
        "Hosseinioun:contribution_score_cs",
        "type_set_alignment_with_metathetic_field, adjacent_possible_participation",
        "",
        "Nestedness contribution score: cs = (N - <N*_s>) / σ_N*_s. cs > 0 means skill reinforces the nested hierarchy; cs < 0 means it deviates from it",
        "Partitions skills into nested (cs > 0, aligned with hierarchy, growth potential) and unnested (cs < 0, outside hierarchy, limited mobility). Five functional categories: general, nested-intermediate, unnested-intermediate, nested-specific, unnested-specific",
        "Type elements with high cs have more metathetic potential (more adjacent-possible pathways). Type elements with low cs are structurally isolated. Should inform the annular distribution for adjacent-element generation: nested elements generate at sweet-spot radius; unnested at periphery",
        "extends"
    ))

    entries.append(build_entry(src, dist,
        "Hosseinioun:wage_premium_foundation_effect",
        "sigma_Xi_effect, affordance_base_primacy",
        "",
        "Wage premiums associated with nested specializations almost fully disappear when controlling for general skill levels. The general skill base drives the premium, not the specialization itself",
        "Unnested specific skills hold labour market value, but their premiums are diminished by lacking the nested dependency foundation. Without sufficient general skills, specialization cannot unlock its economic potential",
        "The general skill base IS the affordance base. Without sufficient Xi (affordance exposure / general skill accumulation), the TAP birth term fires but produces no real growth. Validates the critical Phase 1 gap: sigma must modulate the metathetic growth equation primarily through breadth of foundation",
        "confirms"
    ))

    entries.append(build_entry(src, dist,
        "Hosseinioun:increasing_nestedness_over_time",
        "metathematization, directed_dependency_channel_formation",
        "",
        "Between 2005 and 2019, the skill structure became more nested by all four metrics (overlap index, checkerboard score, temperature, NODF). Increasingly uneven job requirements and growth in high-dependency branches",
        "Deeper nested structure imposes greater constraints on individual career paths, amplifies disparities, and raises new barriers to upward mobility",
        "Maps to metathematization: the temporal process by which the system's own combinatorial history constrains future possibilities. The adjacent possible develops directed dependency channels that funnel future growth, not just expand",
        "extends"
    ))

    entries.append(build_entry(src, dist,
        "Hosseinioun:skill_entrapment",
        "failed_metathematization, demetathesis, inertial_temporal_state",
        "",
        "Workers trapped in unnested skill pathways with long-term wage penalties. Limited English proficiency blocks language-dependent nested skill development, creating demographic skill entrapment",
        "Structural mechanism of inequality: agents that fail to accumulate sufficient general type elements cannot enter the nested expansion region. They persist but cannot grow",
        "Agents failing to accumulate sufficient general type elements to enter the nested expansion region. They persist (don't die) but cannot grow. Maps to the 'inertial' temporal state in the 5-state machine",
        "confirms"
    ))

    entries.append(build_entry(src, dist,
        "Hosseinioun:career_trajectory_stabilization",
        "convergence_to_attractor, TAPS_signature_fixation",
        "",
        "Skill profiles stabilize within first 5 jobs. General skills advance faster early, then nested skills catch up. After ~5 transitions, both growth rates plateau",
        "Agents rapidly find a TAPS signature and settle into it. Whether this is healthy (established state) or pathological (premature hexis) depends on whether the signature is nested (growth potential) or unnested (entrapment)",
        "Maps to the idea that agents rapidly find a TAPS signature and settle into it. The question of healthy stabilization vs. premature hexis depends on nestedness of the signature",
        "confirms"
    ))

    entries.append(build_entry(src, dist,
        "Hosseinioun:nestedness_feasibility_vs_stability",
        "TAP_birth_vs_extinction_tension, feasibility_vs_stability",
        "",
        "From ecology: nested mutualistic networks promote feasibility (more species can coexist) over stability (return to equilibrium after perturbation). Translated: nestedness in skill space promotes larger adjacent possible over stability of existing configurations",
        "Connects ecological nestedness theory to economic skill structure. Tension between feasibility and stability IS the tension between the TAP birth term and the extinction term μ*M",
        "Nestedness in type-set space promotes feasibility of new combinations (larger adjacent possible) over stability of existing configurations. This tension IS the birth vs. extinction tension in sigma-TAP",
        "extends"
    ))

    entries.append(build_entry(src, dist,
        "Hosseinioun:five_functional_categories",
        "type_set_partitioning, nestedness_attribute",
        "",
        "Five skill categories: general, nested-intermediate, unnested-intermediate, nested-specific, unnested-specific. Based on generality group (3 via k-means) crossed with contribution score sign",
        "Suggests type_set elements should carry a nestedness attribute to distinguish growth trajectory (nested accumulation) from entrapment trajectory (unnested accumulation)",
        "Suggests sigma-TAP type_set elements should carry a nestedness attribute. Would allow the model to distinguish agents accumulating nested elements (growth trajectory) from those accumulating unnested elements (entrapment trajectory)",
        "novel"
    ))

    entries.append(build_entry(src, dist,
        "Hosseinioun:heaps_law_bridge",
        "TAP_diversification_rate, taalbi_exponent_calibration",
        "",
        "Diversification follows structured pathways, not random exploration. Connects to Taalbi's Heaps' law (D ~ k^0.587): Youn's nestedness gives the architecture of diversification; Taalbi's exponent gives the rate",
        "Together provides calibration target (Taalbi's exponent) + structural constraint (Youn's nestedness). Architecture + rate = complete diversification model",
        "Youn's nestedness gives the architecture of diversification; Taalbi's exponent gives the rate. Together: calibration target + structural constraint for sigma-TAP",
        "extends"
    ))

    return entries


def jakobs_entries():
    """Build entries from Jakobs integration concepts."""
    src = "jakobs-early"
    dist = "Jakobs_Communicology_2016_Chart.md"
    entries = []

    entries.append(build_entry(src, dist,
        "Jakobs:four_level_message_operations",
        "L_matrix_four_channel, message_operation_hierarchy",
        "",
        "Ascending complexity of message operations across communicological levels: Store (L1, intrapersonal) → Transmit (L2, interpersonal) → Retrieve (L3, group) → Evaluate/Interpret (L4, cultural)",
        "The ascending complexity directly mirrors the L-matrix quadrants: Store (L11) → Transmit (L12) → Retrieve (L21) → Evaluate/Interpret (L22). Each level adds a higher-order operation on messages",
        "Store (L11, intrapersonal) → Transmit (L12, org→env) → Retrieve (L21, env→org) → Evaluate/Interpret (L22, env↔env). Direct mapping of communicological levels to L-matrix channels",
        "confirms"
    ))

    entries.append(build_entry(src, dist,
        "Jakobs:egocentric_sociocentric_split",
        "molar_molecular, arborescent_rhizomatic, filiation_alliance",
        "",
        "Level III (Group) subdivides into egocentric (task group, rule-based, centrifugal, competition, agony, static categories) and sociocentric (affiliation group, role-based, centripetal, cooperation, harmony, dynamic relations)",
        "Structurally parallel to molar/molecular and filiation/alliance distinctions. Egocentric = aggregate parts, centrifugal, categorical, leadership. Sociocentric = organic whole, centripetal, relational, membership",
        "Maps onto arborescent/rhizomatic, filiation/alliance, competitive/cooperative distinctions. Egocentric = centrifugal, categorical, rule-based, aggregate. Sociocentric = centripetal, cooperative, relational, role-based, organic",
        "confirms"
    ))

    entries.append(build_entry(src, dist,
        "Jakobs:space_binding_time_binding",
        "territorial_deterritorialized, Korzybski_binding_dimensions",
        "",
        "Level IV (Culture) subdivides along Korzybski dimensions: space-binding (post-figurative, place community, past-oriented, digital in/out-group, decoding) vs. time-binding (pre-figurative, non-place community, future-oriented, analogue diffusion, incoding)",
        "Maps directly to Emery & Trist's Type II (positional, place-based) vs. Type III/IV (operational, capacity/power-based) environmental types. Space-binding = territory; time-binding = deterritorialization",
        "Space-binding (place community, past orientation, digital in-group/out-group) = territory. Time-binding (non-place community, future orientation, analogue diffusion) = deterritorialization",
        "confirms"
    ))

    entries.append(build_entry(src, dist,
        "Jakobs:meaning_type_rotation",
        "TAPS_signature_cycle, meaning_modality_rotation",
        "",
        "Meaning type rotation across levels: Synesthetic (L1) → Cognitive (L2) → Affective (L3) → Conative (L4). Follows Jakobson's functional hierarchy mapped onto communicological levels",
        "The rotation through meaning types corresponds to the TAPS signature cycle: Synesthetic (T — embodied becoming) → Cognitive (A — being-state) → Affective (P — relational acting) → Conative (S — volitional creating)",
        "Synesthetic (T — embodied becoming), Cognitive (A — being-state), Affective (P — relational acting), Conative (S — volitional creating). The meaning type rotation maps to the TAPS cycle",
        "extends"
    ))

    entries.append(build_entry(src, dist,
        "Jakobs:house_vs_home",
        "facade_vs_face, spatial_vs_existential_dwelling",
        "",
        "House = physical structure (place community, space-binding). Home = existential dwelling (non-place community, time-binding). Both involve 'many to many' communication but with opposite temporal orientations (past vs. future)",
        "House (spatial structure, place community) = facade (exhibited surface). Home (existential dwelling, non-place community) = face (capacity to exceed surface). The distinction captures the difference between spatial-territorial and temporal-professional community",
        "House (spatial structure, place community) corresponds to facade (exhibited surface). Home (existential dwelling, non-place community) corresponds to face (capacity to exceed surface)",
        "extends"
    ))

    entries.append(build_entry(src, dist,
        "Jakobs:cofigurative_postpre_triad",
        "hexis_praxis_metathesis_triad, Mead_figurative_modes",
        "",
        "Cultural level's base is co-figurative (peers learn from peers), subdivided into post-figurative (children learn from forebears, backward-looking) and pre-figurative (adults learn from children, forward-looking). Margaret Mead's three figurative modes",
        "This triadic structure parallels the hexis-praxis-metathesis triad. Co-figurative base = lateral exchange; post-figurative = sedimented past (hexis); pre-figurative = emergent future (metathesis)",
        "The triadic structure (post-figurative/co-figurative/pre-figurative) parallels hexis (sedimented past) / praxis (lateral present) / metathesis (emergent future)",
        "extends"
    ))

    entries.append(build_entry(src, dist,
        "Jakobs:decode_vs_incode",
        "consumption_vs_consummation, reading_vs_writing_world",
        "",
        "Space-binding decodes — extracts Object from Expression (reading the world, O of E). Time-binding incodes — inscribes Object into Action (writing the world, O of A)",
        "Maps to consumption (process-praxis: taking up sedimented structure) vs. consummation (praxis-process: praxis reaching its term). Decode = extracting the already-given; Incode = inscribing the not-yet",
        "Decode (O of E) = consumption (process-praxis, taking up sedimented structure). Incode (O of A) = consummation (praxis-process, praxis reaching its term)",
        "extends"
    ))

    entries.append(build_entry(src, dist,
        "Jakobs:agony_vs_harmony",
        "adversity_coefficient_vs_prosperity_coefficient, competitive_vs_cooperative",
        "",
        "Egocentric group creates agony (competitive struggle); sociocentric group creates harmony (cooperative resonance). Not a value judgment but structural description of two irreducible group orientations",
        "Maps to adversity-coefficient vs. prosperity-coefficient in the project framework. Two irreducible orientations of group process",
        "Maps to the adversity-coefficient vs. prosperity-coefficient. Agony = competitive struggle (adversity). Harmony = cooperative resonance (prosperity). Structural, not evaluative",
        "confirms"
    ))

    return entries


def sartre_praxis_process_entries():
    """Build entries from Sartre CDR2 PraxisProcess KC table + interpretation."""
    src = "sartre-CDR2-praxis"
    dist = "Sartre_CritiqueDR2_1991_PraxisProcess.md"
    entries = []

    entries.append(build_entry(src, dist,
        "Sartre_CritiqueDR2:praxis_process_systematic",
        "sigma_TAP_core_mechanism, feedback_deviation_structure",
        "pp. 272-301",
        "The totalization-of-envelopment grasped as an ongoing synthesis of free praxis and practico-inert process — action producing its own body which turns back on the agent. Analyzed through four formal remarks: (1) entirely human, (2) necessarily deviating, (3) comprehensible through circularity, (4) operative at every level",
        "Central concept of the section. The four numbered remarks extract its universal structure. Every subsequent concept is a determination of praxis-process",
        "The four formal remarks extract the universal structure of sigma-TAP's core mechanism: feedback that is (1) agent-constituted, (2) necessarily deviating, (3) comprehensible only through circularity, (4) scale-invariant from individual to system",
        "confirms"
    ))

    entries.append(build_entry(src, dist,
        "Sartre_CritiqueDR2:costs_of_action",
        "per_agent_energy_budget, fatigue_threshold_diagnostic, mu_damping",
        "pp. 288-291, 283",
        "Every transformation in a field of scarcity involves expenditure of energy, production of waste-products, and reduction of capacity for future action. 'Everything has its cost' — a synthetic principle defining praxis in scarcity",
        "Provides the energetic foundation of circularity. Fatigue is structural: the costs of action are the costs of History. The worker's 'botches' are the individual prototype of systemic deviation",
        "sigma-TAP's μ-damping as energetic cost of type production. Every type combination expends agent capacity. Fatigue = agent's loss of adaptive capacity as type_set grows. Suggests a per-agent energy budget diagnostic alongside the systemic μ",
        "extends"
    ))

    entries.append(build_entry(src, dist,
        "Sartre_CritiqueDR2:feedback_second_level",
        "sigma_second_level_deviation, feedback_impossibility_of_perfect_damping",
        "pp. 283-284",
        "Praxis-process IS a feedback: its consequences react upon its principles. Currently a negative feedback (warps praxis). Could be made into directed circularity, but correction engenders 'reflexive circularity with second-level deviations'",
        "Names the formal structure of deviation-and-reconditioning. The impossibility of escaping second-level deviations = impossibility of eliminating deviation through feedback. Even perfect awareness produces its own costs",
        "sigma-TAP's σ-field IS the 'directed circularity' — feedback that corrects primary deviation (extinction instability) but produces secondary deviations. The impossibility of eliminating second-level deviations is the formal reason why sigma-TAP trajectories are always 'suboptimal'",
        "confirms"
    ))

    entries.append(build_entry(src, dist,
        "Sartre_CritiqueDR2:human_and_anti_human",
        "praxis_antipraxis_unity, dialectic_antidialectic",
        "pp. 282-283, 291",
        "The indissoluble unity of praxis and anti-praxis at the heart of every action. 'Like the Devil according to the Church Fathers, the exteriority of praxis is parasitic, borrowing its efficacy from interiority'",
        "Replaces binary opposition of human/inhuman with dialectical unity. The anti-human is the structural product of the human. 'It is this very unity that makes the man'",
        "The anti-dialectic (extinction instability, μ-scarcity) borrows its efficacy from the dialectic (type growth, agent interaction). The σ-field integrates both into indissoluble unity",
        "confirms"
    ))

    entries.append(build_entry(src, dist,
        "Sartre_CritiqueDR2:dialectic_and_anti_dialectic",
        "sigma_field_deviation_integration, generalized_cancer",
        "p. 285",
        "The dialectic attempts to close over the anti-dialectic, dissolve and assimilate it. Result: 'generalized cancer' — praxis is 'poisoned from within by the anti-dialectic.' The deviation IS the anti-dialectical reconditioning",
        "Names why integration cannot eliminate process. The practico-inert is not dissolved but integrated — and integration deviates the dialectic from within",
        "The TAP equation without σ is the dialectic without anti-dialectic: pure growth that blows up. The σ-field introduces the anti-dialectic (damping, constraint) which 'poisons' the pure dialectic but makes it viable. The 'generalized cancer' = sigma-TAP's deviation from pure TAP growth",
        "confirms"
    ))

    entries.append(build_entry(src, dist,
        "Sartre_CritiqueDR2:meaning_vs_signification",
        "diagnostic_taxonomy, signification_diagnostics_vs_meaning_diagnostics",
        "pp. 293-298",
        "Signification = rational content of an action, atemporal, universalizable (Stalinism-as-a-prototype). Meaning = synthetic unity of signification and deviation grasped in temporal unity, singular (Stalinism-as-a-venture)",
        "Critical distinction for comprehension. Signification can be conceptualized; meaning can only be temporalized. The part of a whole IS that whole — 'not in the determination that produces it, at least in the substance'",
        "Aggregate M_t trajectory is signification (prototype); per-agent L-matrix history is meaning (singular temporal realization). Youn ratio = signification; per-agent diagnostics = meaning. Suggests per-agent diagnostics are primary, not secondary data to be averaged",
        "novel"
    ))

    entries.append(build_entry(src, dist,
        "Sartre_CritiqueDR2:being_in_itself_totalization",
        "experimenter_perspective, parameter_space_as_being_in_itself",
        "pp. 309-310, 317, 319",
        "The ontological status of praxis-process as 'unassimilable and non-recuperable reality' — 'the strict equivalence between the totalization-of-envelopment in the Universe and the Universe in the totalization-of-envelopment'",
        "Against both Hegel (being-in-itself as abstract moment) and humanist idealism (dissolved into being-for-itself). Being-in-itself eludes knowledge on principle",
        "The simulation's being-in-itself is the parameter space, random seed, computational substrate that conditions the run from outside and cannot be known from within. The experimenter IS the Martian — seeing the system's conditioning in exteriority",
        "extends"
    ))

    entries.append(build_entry(src, dist,
        "Sartre_CritiqueDR2:history_riddled_with_holes",
        "extinction_porosity_diagnostic, hole_pattern_analysis",
        "pp. 310-315",
        "Death experienced as absolute exteriority within interiority — 'Its deaths are billions of holes piercing it.' The sole experiential access to being-in-itself from within the field",
        "Every death reveals the fragility of praxis-process and the universal presence of being-in-exteriority. Death produces History (mortal organisms, urgency, fraternity-terror)",
        "Agent extinction events 'riddle History with holes.' The pattern of extinctions is a map of the system's being-in-itself. Each hole reveals conditioning by μ, α, and σ-parameters that the system conceals from within",
        "extends"
    ))

    entries.append(build_entry(src, dist,
        "Sartre_CritiqueDR2:process_praxis",
        "experimenter_perspective, hidden_card_parameter_space",
        "pp. 329-331",
        "The complementary of praxis-process: the totalization grasped in its being-in-itself, 'containing within it its being-for-itself' — the 'hidden card, the reverse side of praxis-process'",
        "Names what we cannot know but must acknowledge. The ontological primacy of being-in-itself is transformed into primacy of History",
        "The complementary pair praxis-process / process-praxis names two irreducible perspectives on sigma-TAP: agents' perspective (interaction within field) and experimenter's perspective (system in parameter conditioning). The 'hidden card' is the parameter space",
        "extends"
    ))

    entries.append(build_entry(src, dist,
        "Sartre_CritiqueDR2:single_and_multiple",
        "TAP_phase_transition, slipping_stitch_dynamics",
        "pp. 332-335",
        "Praxis unifies the multiple, but unification produces new multiplicity requiring fresh unification — 'never to close upon itself.' History appears as 'a brutal rupture of cyclical repetition: i.e. as transcendence and spirality'",
        "Names the ontological engine of History. The 'slipping stitch' — turning and simultaneously fleeing. When organic circularity shatters, its fragments become objects of fresh unification",
        "The TAP phase transition: before it, the system cycles (societies without history); after, the stitch slips and the spiral produces irreversible dynamics. Each combination event breaks potential cycle by introducing irreversible novelty",
        "confirms"
    ))

    entries.append(build_entry(src, dist,
        "Sartre_CritiqueDR2:ontological_limit",
        "agents_cannot_produce_agents, substrate_precondition",
        "pp. 335-336",
        "Organisms can produce only passive syntheses of physico-chemical substances (tools, machines = inert unity sustained by temporarily assembled materials). Life must always be given — 'to sow, seed is needed'",
        "Names the terminal ontological constraint: the agent cannot produce its own substrate. Production of the inert, not of the living",
        "sigma-TAP agents produce types (passive syntheses) but not agents (active syntheses). Agent population is initialization-given, not emergent. Names the most fundamental architectural constraint — the system cannot bootstrap its own substrate",
        "confirms"
    ))

    entries.append(build_entry(src, dist,
        "Sartre_CritiqueDR2:abandonment",
        "being_without_witness, cosmic_indifference",
        "pp. 329, 326-327",
        "The cosmic situation of praxis-process: being-in-the-midst-of-the-world as 'a universe indifferent to its ends.' Abandonment IS the absolute of interiority — grounds the immanent-being of all historical ends",
        "Names the existential consequence of the ontological investigation. The totalization exists in absolute solitude — 'being-without-a-witness.' Not privation but condition of absolute reality",
        "sigma-TAP's simulation exists in 'absolute solitude' — the agents pursue objectives without knowing whether their α, μ, σ-values permit survival. Abandonment names the ontological situation of agents in a system whose parameters may doom it",
        "extends"
    ))

    entries.append(build_entry(src, dist,
        "Sartre_CritiqueDR2:fatigue_threshold",
        "per_agent_fatigue_metric, capacity_degradation_threshold",
        "pp. 287-291",
        "Every action expends energy and produces waste-products (fatigue, toxins) that modify the agent's capacity. 'Once a certain threshold has been crossed, gestures become less precise and less effective.' The worker cannot know his own drift because instruments of awareness are themselves degraded",
        "The individual prototype of systemic deviation. Circularity 'is rooted in what we may term the costs of action.' The worker's blind exhaustion produces 'botches' — deviations inscribed in worked matter as counter-finalities",
        "Maps to sigma-TAP agents whose σ-responsiveness degrades as type_set accumulates. The 'botch' = maladaptive type combination. Suggests a per-agent fatigue metric distinct from ossification: at what type_set size does the agent cross the threshold where combinations begin producing counter-finalities?",
        "novel"
    ))

    return entries


def sartre_singularity_praxis_entries():
    """Build entries from Sartre CDR2 SingularityPraxis KC table + interpretation."""
    src = "sartre-CDR2-singularity"
    dist = "Sartre_CritiqueDR2_1991_SingularityPraxis.md"
    entries = []

    entries.append(build_entry(src, dist,
        "Sartre_CritiqueDR2:singularity_of_praxis",
        "parameter_regime_singularity, specific_multiplicity",
        "pp. 384-385",
        "Human praxis as a specific determination of every possible praxis — singular not by exclusion but by positive comprehension of its organic-inorganic limits",
        "Structural frame of the entire section. The singularity is contingent facticity (scarcity, organic need) producing a necessary structure",
        "sigma-TAP agents as a specific multiplicity — parameters (α, μ, σ, a) determine a specific practical structure. Each run is a singularization of every possible praxis. Ontological justification for studying one parameter regime at a time",
        "confirms"
    ))

    entries.append(build_entry(src, dist,
        "Sartre_CritiqueDR2:non_transcendable_aim",
        "sigma_as_viability_condition, extinction_avoidance_as_non_transcendable",
        "pp. 385-386, 389-390",
        "Preservation of life as the absolute end that cannot be relativized or subordinated. Even 'gratuitous' acts ultimately suspend from this aim",
        "Grounds the entire practico-inert apparatus. Division of labour, machines, alienation, revolution all derive urgency from organic need",
        "σ-modulation as the formal expression of life-preservation. σ IS the mechanism by which the system pursues the non-transcendable aim — without it, the system blows up. Not optimization but viability maintenance: a threshold condition, not a target function",
        "confirms"
    ))

    entries.append(build_entry(src, dist,
        "Sartre_CritiqueDR2:organic_hexis",
        "type_set_as_hexis, sedimented_practical_orientation",
        "pp. 347-349, 387",
        "Sedimented practical orientation — 'passive synthesis supported by the living synthesis' — constituting the agent as distinct from the organism. The agent has 'a twofold status: dissolved as acting; remains as hexis'",
        "Mediates between pure biology and pure agency. Occupational deformations, technical skills, bodily modifications are hexis",
        "The agent's accumulated type_set IS its hexis — not a random collection but structured history of interactions, constituting the agent as this particular agent with these capacities and vulnerabilities. Names what the type_set is ontologically",
        "extends"
    ))

    entries.append(build_entry(src, dist,
        "Sartre_CritiqueDR2:practical_field_real_body",
        "L_matrix_four_channel, practical_field_as_agent_body",
        "pp. 383-384",
        "The totalization of all surrounding elements as possible means/risks — 'the matrix of real means.' Not a spatial container but a practical category: 'mediation, milieu, intermediary, and means designate one single reality'",
        "The field IS the agent's exteriority-as-body. Four terms designate one single reality",
        "The L-matrix's four channels (L11, L12, L21, L22) constitute the agent's practical field. The convergence is structural: the practical field totalizes all surrounding elements as means/risks, which is exactly what the L-matrix tracks",
        "confirms"
    ))

    entries.append(build_entry(src, dist,
        "Sartre_CritiqueDR2:knowledge_creation_invention",
        "adjacent_possible_constitution_not_discovery, anti_positivist_TAP",
        "pp. 357-362",
        "Knowledge is not contemplation but praxis — 'the invention of a practical unification of the practical field.' 'Invention is the real structure of discovery'",
        "Collapses theory/practice distinction. Perception selects, organizes, totalizes the field toward an objective. The Discovery of America demonstrates: the object was constituted by practical unification, not revealed",
        "Type combination IS knowledge-as-praxis: each new type is invention (practical unification), not discovery. The adjacent possible is constituted by the combination event, not revealed by it. Challenges Kauffman's implicit positivism",
        "extends"
    ))

    entries.append(build_entry(src, dist,
        "Sartre_CritiqueDR2:analytic_vs_dialectical_reason",
        "diagnostic_framework_analytic_dialectical, TAP_equation_as_positive_reason",
        "pp. 373-377, 385",
        "Analytic (positive, combinatory) Reason: intelligibility proper to machines — fully decomposable, transparent, predictable. Dialectical Reason: irreducible temporalizing movement grasping action as unification-in-progress, never definable by result",
        "Not two competing epistemologies but two moments within praxis. The machine IS analytic Reason realized in inert matter. Its limit: cannot grasp totalizing, temporal, irreversible character of living action",
        "TAP equation = positive/analytic Reason (combinatorial growth law, transparent). sigma-TAP's full dynamics = dialectical Reason (σ-modulation, per-agent interaction, TAPS — totalizing, irreversible, comprehensible but not decomposable). Principled criterion for diagnostic mode selection",
        "novel"
    ))

    entries.append(build_entry(src, dist,
        "Sartre_CritiqueDR2:two_types_praxis",
        "exterior_interior_type_distinction, product_vs_capacity_modifier",
        "pp. 378-380",
        "Exterior replacement: machine substitutes for the whole operation (autonomous substitute). Interior replacement: tool/prosthesis extends or replaces an organ (extension of the body). Both produce governed circularity",
        "Structural distinction generating the machine-organism dialectic. Exterior tends toward autonomous positive Reason; interior maintains organic governance",
        "Suggests type combinations could be qualitatively distinguished: 'product types' (exterior — inert syntheses entering M_t) vs. 'capacity-modifier types' (interior — types changing agent's future interaction profile). Maps TAPS at structural-effect level",
        "novel"
    ))

    entries.append(build_entry(src, dist,
        "Sartre_CritiqueDR2:governed_circularity",
        "sigma_field_governed_feedback, non_transcendable_aim_as_viability_condition",
        "pp. 380-383",
        "Feedback structure where the product re-conditions the producer, under governance of the non-transcendable aim. Not mere cybernetic feedback: the circularity is governed by the organic aim",
        "Distinguishes sigma-TAP from both bare TAP (wild circularity, no feedback) and pure cybernetic model (mechanical circularity, feedback without organic governance). The governed character means σ-modulation can never be autonomous",
        "sigma-TAP's σ-field produces governed circularity: feedback corrects deviation but governance comes from the viability condition, not the mechanism. Distinguishes sigma-TAP from bare TAP (wild) and pure cybernetics (mechanical)",
        "confirms"
    ))

    entries.append(build_entry(src, dist,
        "Sartre_CritiqueDR2:transitivity_of_action",
        "path_dependent_irreversibility, relation_persistence",
        "pp. 391-392",
        "Action is neither permanence (inert) nor repetition (organic) but irreversible unification — 'the quartering of the cyclical by changes of exteriority.' The restored organism is always other in an other milieu — only the relation can remain identical",
        "Names the ontological status of action — its specific temporality. The dialectic 'asserts itself as a temporalizing synthesis which unifies itself by unifying'",
        "sigma-TAP's simulation is irreversible: each step produces an other system. Functional relations (α, μ, σ) remain constant but the system state is always other. Why trajectories are path-dependent",
        "confirms"
    ))

    entries.append(build_entry(src, dist,
        "Sartre_CritiqueDR2:stasis_alienating_halt",
        "snapshot_diagnostic_warning, Taylorization_of_diagnostics",
        "pp. 391-392",
        "The social order defining the agent by the product — e.g., the worker defined by 'the number of needles he fixes hourly.' Gives 'the dead unity of a passive synthesis for the real movement of unification'",
        "Taylorization as ontological arrest — freezing unification into result. But 'praxis refuses to let itself be limited to that'",
        "Any snapshot diagnostic defining the system by current M_t or Youn ratio commits the alienating halt. Per-step diagnostics are necessary stases of totalization, not the totalization itself. Must track the movement, not freeze it",
        "novel"
    ))

    entries.append(build_entry(src, dist,
        "Sartre_CritiqueDR2:historical_materialism_intelligibility",
        "mu_scarcity_as_ground, TAPS_sector_autonomy_plus_need",
        "pp. 390-391",
        "The twofold determination of praxis: relative autonomy of practical sectors + determination of the whole action by the need which it transcends to satisfy. 'Scarcity lived in interiority by the organ is the inorganic producing itself as negative determination'",
        "Not a doctrine but the intelligibility discovered through comprehension of organic-inorganic mediation",
        "sigma-TAP's μ-parameter IS scarcity lived in interiority. Each TAPS modality has its own dynamics (relative autonomy) but all are suspended from μ-scarcity (determination by need). The twofold determination IS the TAPS architecture",
        "confirms"
    ))

    return entries


def main():
    entries = []
    entries.extend(hosseinioun_entries())
    entries.extend(jakobs_entries())
    entries.extend(sartre_praxis_process_entries())
    entries.extend(sartre_singularity_praxis_entries())

    output = sys.argv[1] if len(sys.argv) > 1 else None
    data = json.dumps(entries, indent=2, ensure_ascii=False)

    if output:
        with open(output, 'w', encoding='utf-8') as f:
            f.write(data)
        print(f"Wrote {len(entries)} entries to {output}", file=sys.stderr)
    else:
        print(data)


if __name__ == "__main__":
    main()
