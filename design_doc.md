# Graph Schema Design

## Question

Should the graph use one physical node/edge type with type properties, or multiple
physical node/edge types?

## Node Design

The project currently uses one node type:

```text
(:Entity {
  entity_type: "file" | "class" | "function" | "method"
})
```

The planned graph needs these node meanings:

- `file`
- `class`
- `function`
- `method`

There are two main ways to represent those meanings.

### Option 1: Single Physical Node Type

Use one physical node type, `Entity`, and store the meaning in a property:

```text
(:Entity { entity_type: "file" })
(:Entity { entity_type: "method" })
```

In this model, the database sees every node as the same type. The application decides what
the node means by reading `entity_type`.

#### Benefits

- Simple to implement from the current schema.
- Easy to add a new logical node kind during experimentation.
- One insert path can handle files, classes, functions, and methods.
- Generic traversal works naturally across all code entities.
- Shared fields such as `id`, `label`, `file_path`, and `source_location` stay uniform.

#### Costs

- Queries need property filters when they only want one logical node kind.
- Invalid `entity_type` strings are easier to insert unless the application validates them.
- Type-specific fields are awkward because every node shares the same physical schema.
- The database cannot enforce file-only or method-only constraints as strongly.

Example query:

```cypher
MATCH (n:Entity)
WHERE n.entity_type = "method" AND n.label = $name
RETURN n
```

### Option 2: Multiple Physical Node Types

Use separate physical node types for stable node kinds:

```text
(:File)
(:Class)
(:Function)
(:Method)
```

In this model, the node meaning is part of the graph schema itself.

#### Benefits

- Queries are clearer and more direct.
- Type-specific fields and constraints are easier to model.
- Invalid node kinds are harder to create accidentally.
- The schema communicates the graph model more explicitly.

#### Costs

- More schema and insertion code.
- Generic traversal needs to handle multiple node labels/types.
- Adding a new node kind requires a schema/code change.
- Shared fields must be repeated or coordinated across node types.
- Less flexible while the node model is still evolving.

Example query:

```cypher
MATCH (m:Method)
WHERE m.label = $name
RETURN m
```

### Node Comparison

| Dimension | Single `Entity` node | Multiple node types |
|---|---|---|
| Where meaning lives | `entity_type` property | Node type/schema |
| Flexibility | High | Medium |
| Query readability | Medium | High |
| Schema complexity | Low | Medium |
| Type-specific fields | Awkward | Natural |
| Generic traversal | Simple | More explicit handling |
| Best fit | Early MVP and shared entity fields | Stable model with type-specific behavior |

### Node Recommendation

For v1, use the current single-node model:

```text
Entity { entity_type: "file" | "class" | "function" | "method" }
```

The planned node kinds share the same core fields, and the project is still validating the
graph model. Multiple physical node types become more attractive later if files, classes,
functions, methods, tests, packages, or modules need different fields, constraints, or
query paths.

## Edge Design

The project currently uses one edge type:

```text
(:Entity)-[:RELATES { relation: "contains" }]->(:Entity)
```

The planned graph needs more relationship meanings:

- `contains`
- `imports`
- `exports`
- `calls`
- `referenced_by`
- `member_of`

There are two main ways to represent those meanings.

### Option 1: Single Physical Edge Type

Use one physical edge type, `RELATES`, and store the meaning in a property:

```text
(:Entity)-[:RELATES { relation: "calls" }]->(:Entity)
(:Entity)-[:RELATES { relation: "imports" }]->(:Entity)
```

In this model, the database sees every edge as the same type. The application decides what
the edge means by reading `relation`.

#### Benefits

- Simple to implement from the current schema.
- Easy to add a new relation value during experimentation.
- One insert path can handle every relationship.
- Shared metadata such as `confidence`, `source`, and `details` is straightforward.

#### Costs

- Queries are less clear because every relation needs a property filter.
- Invalid relation strings are easier to insert unless the application validates them.
- The database cannot optimize or enforce each relationship kind as strongly.
- As the graph grows, filtering generic edges may become less efficient than targeting a
  specific edge type.

Example query:

```cypher
MATCH (a:Entity)-[r:RELATES]->(b:Entity)
WHERE r.relation = "calls" AND a.id = $id
RETURN b
```

### Option 2: Multiple Physical Edge Types

Use separate physical edge types for each stable relationship:

```text
(:Entity)-[:CONTAINS]->(:Entity)
(:Entity)-[:IMPORTS]->(:Entity)
(:Entity)-[:CALLS]->(:Entity)
```

In this model, the relationship meaning is part of the graph schema itself.

#### Benefits

- Queries are clearer and more direct.
- The database can target a specific relationship type/table.
- Invalid relation kinds are harder to create accidentally.
- The schema communicates the graph model more explicitly.

#### Costs

- More schema and insertion code.
- Adding a new relationship kind requires a schema/code change.
- Shared metadata fields must be repeated across edge types.
- Less flexible while the relation set is still changing.

Example query:

```cypher
MATCH (a:Entity)-[:CALLS]->(b:Entity)
WHERE a.id = $id
RETURN b
```

### Edge Comparison

| Dimension | Single `RELATES` edge | Multiple edge types |
|---|---|---|
| Where meaning lives | `relation` property | Edge type/schema |
| Flexibility | High | Medium |
| Query readability | Medium | High |
| Schema complexity | Low | Medium |
| Application validation need | Higher | Lower |
| Performance ceiling | Lower for large graphs | Higher for stable queries |
| Best fit | Early MVP and experimentation | Stable graph model |

### Edge Recommendation

For the first implementation, either option is viable.

If the goal is the fastest low-risk MVP, keep the current physical model:

```text
RELATES { relation: "...", confidence: ..., source: ... }
```

This minimizes migration work and lets the relation set evolve.

If the project is ready to treat `contains`, `imports`, `exports`, `calls`,
`referenced_by`, and `member_of` as stable core relationships, use multiple physical edge
types instead. That is cleaner for graph traversal and likely better long term.

Practical default:

- Use single `RELATES` while validating the graph model.
- Keep relation values strict in application code.
- Revisit typed edges once the core relation set has proven stable.
