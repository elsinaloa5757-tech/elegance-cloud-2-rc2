import { createClient } from "https://esm.sh/@supabase/supabase-js@2";
const EXPECTED_HASH="6f652a2a8f68c36018fdf64eeee9f7ae89d7b4c1f4d0737b61a73779048899f1";
const cors={"Access-Control-Allow-Origin":"*","Access-Control-Allow-Headers":"content-type,x-elegance-sync-key","Access-Control-Allow-Methods":"POST,OPTIONS"};
const out=(v:unknown,s=200)=>new Response(JSON.stringify(v),{status:s,headers:{...cors,"content-type":"application/json"}});
async function shaBytes(bytes:Uint8Array){const d=await crypto.subtle.digest("SHA-256",bytes);return [...new Uint8Array(d)].map(x=>x.toString(16).padStart(2,"0")).join("")}
async function sha(v:string){return shaBytes(new TextEncoder().encode(v))}
function bytesToBase64(bytes:Uint8Array){let value="";const size=32768;for(let i=0;i<bytes.length;i+=size)value+=String.fromCharCode(...bytes.subarray(i,i+size));return btoa(value)}
const slug=(v:string)=>v.toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g,"").replace(/[^a-z0-9]+/g,"-").replace(/^-|-$/g,"").slice(0,100)||crypto.randomUUID();
Deno.serve(async req=>{
 if(req.method==="OPTIONS")return new Response("ok",{headers:cors});
 if(req.method!=="POST")return out({error:"method_not_allowed"},405);
 if(await sha(req.headers.get("x-elegance-sync-key")||"")!==EXPECTED_HASH)return out({error:"unauthorized"},401);
 try{
  const b=await req.json();
  const sb=createClient(Deno.env.get("SUPABASE_URL")!,Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!,{auth:{persistSession:false}});
  if(b.action==="ping")return out({ok:true,service:"elegance-sync",version:"2.0-storage-manager"});
  if(b.action==="storage_upload"){
   const o=b.object||{}; const bucket=String(o.bucket||"elegance-private"); const path=String(o.object_path||"");
   const bytes=Uint8Array.from(atob(String(o.base64||"")),c=>c.charCodeAt(0)); const digest=await shaBytes(bytes);
   if(digest!==String(o.sha256||""))return out({ok:false,error:"sha256_mismatch_before_upload"},400);
   const gb=await sb.storage.getBucket(bucket); if(gb.error){const cb=await sb.storage.createBucket(bucket,{public:bucket==="elegance-public",fileSizeLimit:52428800});if(cb.error && !String(cb.error.message||"").toLowerCase().includes("already"))throw cb.error;} const up=await sb.storage.from(bucket).upload(path,bytes,{contentType:String(o.content_type||"application/octet-stream"),upsert:true}); if(up.error)throw up.error;
   const meta={id:String(o.id||crypto.randomUUID()),product_id:String(o.product_id||""),variant:String(o.variant||"original"),sha256:digest,size_bytes:bytes.length,content_type:String(o.content_type||"application/octet-stream"),bucket,object_path:path,verified_at:new Date().toISOString()};
   const url=bucket==="elegance-public"?`${Deno.env.get("SUPABASE_URL")}/storage/v1/object/public/${bucket}/${path}`:null;
   const manifest=await sb.from("elegance_storage_objects").upsert({local_object_id:meta.id,product_id:meta.product_id,variant:meta.variant,sha256:meta.sha256,size_bytes:meta.size_bytes,content_type:meta.content_type,bucket:meta.bucket,object_path:meta.object_path,public_url:url,verified:true,verified_at:meta.verified_at,updated_at:meta.verified_at},{onConflict:"local_object_id"});if(manifest.error)throw manifest.error;
   return out({ok:true,object:{...meta,url}});
  }
  if(b.action==="storage_download"){
   const bucket=String(b.bucket||""); const path=String(b.object_path||""); const dl=await sb.storage.from(bucket).download(path); if(dl.error)throw dl.error;
   const bytes=new Uint8Array(await dl.data.arrayBuffer()); return out({ok:true,base64:bytesToBase64(bytes),sha256:await shaBytes(bytes),size_bytes:bytes.length});
  }
  if(b.action==="storage_inventory"){const rows=await sb.from("elegance_storage_objects").select("local_object_id,product_id,variant,sha256,size_bytes,content_type,bucket,object_path,public_url,verified,verified_at").order("updated_at",{ascending:false}).limit(5000);if(rows.error)throw rows.error;return out({ok:true,count:rows.data.length,objects:rows.data,source:"supabase_manifest"})}
  if(b.action==="storage_cleanup_orphans") return out({ok:true,dry_run:true,count:0,orphans:[],message:"La limpieza destructiva requiere confirmación desde el manifiesto local."});
  const products=Array.isArray(b.products)?b.products:[];const results=[];
  for(const p of products){const id=String(p.id||crypto.randomUUID());const s=String(p.slug||slug(String(p.title||p.name||id)));const uploaded=[];
   for(const im of (Array.isArray(p.image_uploads)?p.image_uploads:[])){const ext=String(im.extension||"webp").replace(/[^a-z0-9]/gi,"").toLowerCase()||"webp";const path=`products/${id}/${slug(String(im.filename||"image"))}.${ext}`;const bytes=Uint8Array.from(atob(String(im.base64||"")),c=>c.charCodeAt(0));const r=await sb.storage.from("elegance-public").upload(path,bytes,{contentType:String(im.content_type||"image/webp"),upsert:true});if(r.error)throw r.error;uploaded.push(`${Deno.env.get("SUPABASE_URL")}/storage/v1/object/public/elegance-public/${path}`)}
   const images=[...uploaded,...(Array.isArray(p.images)?p.images:[])].filter(Boolean);const row={id,slug:s,title:String(p.title||p.name||"Producto"),description:String(p.description||""),brand:String(p.brand||""),model:String(p.model||""),category:String(p.category||"Otros"),subcategory:String(p.subcategory||""),gender:String(p.gender||""),sizes:Array.isArray(p.sizes)?p.sizes:[],colors:Array.isArray(p.colors)?p.colors:[],keywords:Array.isArray(p.keywords)?p.keywords:[],stock:Number(p.stock||0),available:Boolean(p.available??Number(p.stock||0)>0),low_stock:Boolean(p.low_stock||false),price:Number(p.price||0),promotion_price:p.promotion_price==null?null:Number(p.promotion_price),effective_price:Number(p.effective_price??p.promotion_price??p.price??0),featured:Boolean(p.featured||false),status:String(p.status||"published"),images,share_url:`https://elegance-public-catalog.vercel.app/product.html?slug=${encodeURIComponent(s)}`,source_updated_at:p.source_updated_at||new Date().toISOString(),synced_at:new Date().toISOString(),source_hash:String(p.source_hash||"")};
   const save=await sb.from("elegance_public_products").upsert(row,{onConflict:"id"}).select("id,slug,synced_at").single();if(save.error)throw save.error;results.push({...save.data,images});}
  return out({ok:true,count:results.length,results});
 }catch(e){return out({ok:false,error:e instanceof Error?e.message:String(e)},500)}
});
