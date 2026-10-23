/**
 * The web API, typed from the server's own OpenAPI document (#590). `schema.d.ts` is generated from `openapi.json`, which the server writes
 * (`npm run api`; a Python test and a Vitest test fail when either is stale), so a route that is renamed or removed on the server is a build error here.
 *
 *   const access = await api.get("/api/access")
 *   await api.put("/api/access/password", {}, { current, new: next })
 *   await api.get("/api/datasource/{id}/lookups/{lookup}", { path: { id, lookup } })
 *
 * The path is one of the document's, for that method; its parameters are required when it has any and are encoded into it; the answer is the route's
 * declared type (`unknown` until the route declares a response model). Everything goes through ApiClient, so signing in, the session and the server's
 * message on a failure work as for any other call.
 */
import type { paths } from "./schema"
import { apiDelete, apiJson, apiPatch, apiPost, apiPut, joinUrl } from "../components/ApiClient"

type Method = "get" | "post" | "put" | "patch" | "delete"
/** The paths that have this method (an absent method is `?: never` in the generated types). */
export type PathsWith<M extends Method> = { [P in keyof paths]: paths[P] extends { [K in M]: object } ? P : never }[keyof paths]
type Operation<P extends keyof paths, M extends Method> = paths[P] extends { [K in M]: infer O } ? O : never
/** What a successful call answers: the 200 (or 201) JSON body the route declares, else `unknown`. */
export type Answer<O> = O extends { responses: { 200: { content: { "application/json": infer T } } } } ? T
	: O extends { responses: { 201: { content: { "application/json": infer T } } } } ? T : unknown
/** What a call sends: the JSON body the route declares, else `unknown`. */
export type Body<O> = O extends { requestBody: { content: { "application/json": infer B } } } ? B
	: O extends { requestBody?: { content: { "application/json": infer B } } } ? B | undefined : unknown
type PathParams<O> = O extends { parameters: { path: infer PP } } ? PP : never
type QueryParams<O> = O extends { parameters: { query?: infer Q } } ? Q : never
/** A call's options: `path` is required when the route has path parameters, `query` when it declares one. */
export type Options<O> = ([PathParams<O>] extends [never] ? { path?: never } : { path: PathParams<O> }) & ([QueryParams<O>] extends [never] ? { query?: never } : { query?: QueryParams<O> })
type OptionArgs<O> = [PathParams<O>] extends [never] ? [options?: Options<O>] : [options: Options<O>]

const BASE = import.meta.env.VITE_API_URL ?? "/"
/** The options as the address builder reads them (the typed `Options` of a route are narrower). */
type CallOptions = { path?: Record<string, unknown>, query?: Record<string, unknown> }

/** The address of a call: the path with its parameters filled in (each encoded), and the query, under the API's base. */
export function apiUrl(path: string, options?: CallOptions): string {
	const filled = path.replace(/\{([^}]+)\}/g, (_, name: string) => {
		const value = options?.path?.[name]
		if (value === undefined || value === null) throw new Error(`The path ${path} needs ${name}`)
		return encodeURIComponent(String(value))
	})
	const query = new URLSearchParams()
	for (const [key, value] of Object.entries(options?.query ?? {})) {
		if (value !== undefined && value !== null) query.append(key, String(value))
	}
	const search = query.toString()
	return joinUrl(BASE, filled.replace(/^\//, "")) + (search ? `?${search}` : "")
}

export const api = {
	get<P extends PathsWith<"get">>(path: P, ...args: OptionArgs<Operation<P, "get">>): Promise<Answer<Operation<P, "get">>> {
		return apiJson(apiUrl(path, args[0] as CallOptions | undefined))
	},
	post<P extends PathsWith<"post">>(path: P, options: Options<Operation<P, "post">>, body: Body<Operation<P, "post">>): Promise<Answer<Operation<P, "post">>> {
		return apiPost(apiUrl(path, options as CallOptions), body)
	},
	put<P extends PathsWith<"put">>(path: P, options: Options<Operation<P, "put">>, body: Body<Operation<P, "put">>): Promise<Answer<Operation<P, "put">>> {
		return apiPut(apiUrl(path, options as CallOptions), body)
	},
	patch<P extends PathsWith<"patch">>(path: P, options: Options<Operation<P, "patch">>, body: Body<Operation<P, "patch">>): Promise<Answer<Operation<P, "patch">>> {
		return apiPatch(apiUrl(path, options as CallOptions), body)
	},
	delete<P extends PathsWith<"delete">>(path: P, ...args: OptionArgs<Operation<P, "delete">>): Promise<Answer<Operation<P, "delete">>> {
		return apiDelete(apiUrl(path, args[0] as CallOptions | undefined))
	},
}
